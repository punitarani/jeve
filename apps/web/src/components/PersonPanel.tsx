"use client";

/**
 * Why an agent did what it did.
 *
 * This is where the research question stops being a claim. A decision row
 * carries the distribution the policy produced *and* the draw taken from it,
 * so you can see both what was thought and what the dice did — and, once Jev
 * is wired in, whether two people in the same situation actually differ.
 *
 * Whose decisions is a search, not a list: the district has two hundred and
 * twenty-five staff, and a listbox of them was a scroll nobody finished. The
 * input asks `/persons?q=` for a name or a role and shows a screenful.
 */
import { useEffect, useState } from "react";
import type { Decision, Person } from "@jeve/contracts";
import { fetchDecisions, searchPersons } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";

/** How long the input rests before a keystroke becomes a request. */
const SEARCH_DEBOUNCE_MS = 250;
/** What one search brings back: a screenful, never the roster. */
const SEARCH_LIMIT = 30;

export function PersonPanel() {
	const [query, setQuery] = useState("");
	const [results, setResults] = useState<Person[]>([]);
	const [open, setOpen] = useState(false);
	const [selected, setSelected] = useState<string | null>(null);
	const [decisions, setDecisions] = useState<Decision[]>([]);
	const [person, setPerson] = useState<Person | null>(null);
	const [error, setError] = useState<string | null>(null);

	// The query, once it has rested. The empty query runs too, on mount, so
	// the panel opens on somebody rather than on nothing: the first person
	// the API lists is picked until the reader picks another.
	useEffect(() => {
		let live = true;
		const timer = setTimeout(() => {
			searchPersons(query, undefined, undefined, SEARCH_LIMIT)
				.then((body) => {
					if (!live) return;
					setResults(body.persons);
					setError(null);
					setSelected((current) => current ?? body.persons[0]?.id ?? null);
				})
				// Swallowing this would leave an empty list with no explanation,
				// which is how a contract mismatch turns into a mystery.
				.catch((e: unknown) => live && setError(String(e)));
		}, SEARCH_DEBOUNCE_MS);
		return () => {
			live = false;
			clearTimeout(timer);
		};
	}, [query]);

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

	const pick = (p: Person) => {
		setSelected(p.id);
		setOpen(false);
	};

	return (
		<Card size="sm" data-testid="person-panel">
			<CardHeader>
				<CardTitle className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
					People — what they decided, and how
				</CardTitle>
			</CardHeader>
			<CardContent>
				{error && (
					<p
						className="mb-2.5 text-xs text-destructive"
						data-testid="person-error"
					>
						{error}
					</p>
				)}
				<div className="relative mb-2.5">
					<input
						type="text"
						role="combobox"
						aria-expanded={open}
						aria-controls="person-options"
						aria-autocomplete="list"
						autoComplete="off"
						placeholder="search staff by name or role"
						value={query}
						onChange={(event) => {
							setQuery(event.target.value);
							setOpen(true);
						}}
						onFocus={() => setOpen(true)}
						onBlur={() => setOpen(false)}
						onKeyDown={(event) => {
							if (event.key === "Escape") setOpen(false);
						}}
						className="flex h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
						data-testid="person-select"
					/>
					{open && results.length > 0 && (
						<ul
							id="person-options"
							role="listbox"
							className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-border bg-popover p-1 text-sm shadow-md"
							data-testid="person-options"
						>
							{results.map((p) => (
								<li
									key={p.id}
									role="option"
									aria-selected={p.id === selected}
									// mousedown would move focus off the input, whose blur
									// closes this list before the click lands on it.
									onMouseDown={(event) => event.preventDefault()}
									onClick={() => pick(p)}
									className="cursor-pointer rounded-md px-2 py-1 hover:bg-muted aria-selected:bg-muted"
								>
									{describe(p)}
								</li>
							))}
						</ul>
					)}
					{open && results.length === 0 && query !== "" && (
						<p
							className="absolute z-20 mt-1 w-full rounded-lg border border-border bg-popover px-2.5 py-1.5 text-xs text-muted-foreground shadow-md"
							data-testid="person-none"
						>
							Nobody on the staff matches &ldquo;{query}&rdquo;.
						</p>
					)}
				</div>

				{person !== null && (
					<p className="muted fineprint" data-testid="person-picked">
						{describe(person)}
						{person.traits && (
							<>
								{" "}
								· traits:{" "}
								{Object.entries(person.traits)
									.map(([k, v]) => `${k} ${v.toFixed(2)}`)
									.join(" · ")}
							</>
						)}
					</p>
				)}

				{decisions.length === 0 ? (
					<p className="muted" data-testid="no-decisions">
						No decisions recorded yet for this person.
					</p>
				) : (
					<Table data-testid="decision-table">
						<TableHeader>
							<TableRow className="hover:bg-transparent">
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									when
								</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									question
								</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">by</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									chose
								</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									draw
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{decisions.slice(0, 12).map((d) => {
								const draw = Object.values(d.draws)[0];
								return (
									<TableRow
										key={d.id}
										data-testid="decision-row"
										className="hover:bg-transparent"
									>
										<TableCell className="px-1.5 py-1 text-xs text-muted-foreground">
											{d.label}
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											{d.question_set}
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											<Badge variant="outline">{d.source}</Badge>
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											{summarise(d.chosen)}
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											{typeof draw === "number" ? (
												<Tooltip>
													<TooltipTrigger
														render={
															<span className="inline-flex cursor-default items-center gap-1.5" />
														}
													>
														<Progress
															value={Math.round(draw * 100)}
															className="w-12 [&_[data-slot=progress-track]]:h-1.5"
														/>
														<span className="text-muted-foreground">
															{draw.toFixed(2)}
														</span>
													</TooltipTrigger>
													<TooltipContent className="font-mono">
														{d.prng_path}
													</TooltipContent>
												</Tooltip>
											) : (
												<span className="muted">—</span>
											)}
										</TableCell>
									</TableRow>
								);
							})}
						</TableBody>
					</Table>
				)}
				<p className="muted fineprint">
					Rules decisions carry a draw but no distribution. Once typed decisions
					are wired in, the distribution appears beside the draw and this table
					answers the project&apos;s actual question.
				</p>
			</CardContent>
		</Card>
	);
}

/** One line for the picker: who, what they do, where — and which team, when they have one. */
function describe(p: Person): string {
	const team = p.team_id === null ? "" : ` / ${p.team_id}`;
	return `${p.name} — ${p.role} @ ${p.org_id}${team}`;
}

function summarise(chosen: Record<string, unknown>): string {
	return Object.entries(chosen)
		.filter(([, v]) => v !== null && v !== undefined)
		.map(([k, v]) =>
			typeof v === "boolean" ? (v ? k : `no ${k}`) : `${k}=${v}`,
		)
		.join(", ");
}
