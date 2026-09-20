"use client";

/**
 * Why an agent did what it did.
 *
 * This is where the research question stops being a claim. A decision row
 * carries the distribution the policy produced *and* the draw taken from it,
 * so you can see both what was thought and what the dice did — and, once Jev
 * is wired in, whether two people in the same situation actually differ.
 */
import { useEffect, useState } from "react";
import type { Decision, Person } from "@jeve/contracts";
import { fetchDecisions, fetchPersons } from "@/lib/api";

export function PersonPanel() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [person, setPerson] = useState<Person | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPersons()
      .then((body) => {
        setPersons(body.persons);
        if (body.persons.length > 0 && selected === null) {
          setSelected(body.persons[0]!.id);
        }
      })
      // Swallowing this would leave an empty dropdown with no explanation,
      // which is how a contract mismatch turns into a mystery.
      .catch((e: unknown) => setError(String(e)));
  }, [selected]);

  useEffect(() => {
    if (selected === null) return;
    fetchDecisions(selected)
      .then((body) => {
        setPerson(body.person);
        setDecisions(body.decisions);
        setError(null);
      })
      .catch((e: unknown) => setError(String(e)));
  }, [selected]);

  return (
    <section className="panel" data-testid="person-panel">
      <h2>People — what they decided, and how</h2>
      {error && (
        <p className="pill down" data-testid="person-error">
          {error}
        </p>
      )}
      <select
        data-testid="person-select"
        value={selected ?? ""}
        onChange={(e) => setSelected(e.target.value)}
        style={{
          background: "#0e1116",
          color: "inherit",
          border: "1px solid var(--line)",
          borderRadius: 4,
          padding: "4px 8px",
          font: "inherit",
          width: "100%",
          marginBottom: 10,
        }}
      >
        {persons.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} — {p.role} @ {p.org_id}
          </option>
        ))}
      </select>

      {person?.traits && (
        <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
          traits:{" "}
          {Object.entries(person.traits)
            .map(([k, v]) => `${k} ${v.toFixed(2)}`)
            .join(" · ")}
        </p>
      )}

      {decisions.length === 0 ? (
        <p className="muted" data-testid="no-decisions">
          No decisions recorded yet for this person.
        </p>
      ) : (
        <table data-testid="decision-table">
          <thead>
            <tr>
              <th>when</th>
              <th>question</th>
              <th>by</th>
              <th>chose</th>
              <th>draw</th>
            </tr>
          </thead>
          <tbody>
            {decisions.slice(0, 12).map((d) => {
              const draw = Object.values(d.draws)[0];
              return (
                <tr key={d.id} data-testid="decision-row">
                  <td className="muted">{d.label}</td>
                  <td>{d.question_set}</td>
                  <td>
                    <span className="pill">{d.source}</span>
                  </td>
                  <td>{summarise(d.chosen)}</td>
                  <td>
                    {typeof draw === "number" ? (
                      <span title={d.prng_path}>
                        <span
                          className="bar"
                          style={{ width: `${Math.round(draw * 48)}px` }}
                        />{" "}
                        {draw.toFixed(2)}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
        Rules decisions carry a draw but no distribution. Once typed decisions
        are wired in, the distribution appears beside the draw and this table
        answers the project&apos;s actual question.
      </p>
    </section>
  );
}

function summarise(chosen: Record<string, unknown>): string {
  return Object.entries(chosen)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => (typeof v === "boolean" ? (v ? k : `no ${k}`) : `${k}=${v}`))
    .join(", ");
}
