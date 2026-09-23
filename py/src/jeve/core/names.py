"""Names for the people the seed makes up.

Two hundred and twenty-five members of staff cannot be named by hand, and a
name is the one thing about a person that a viewer reads before anything else.
So a name is drawn from these pools by a path that is about the person
(CORE-0009): the same id gets the same name on every machine, and adding a
name to a pool moves nobody who already exists, because the pools are only
ever appended to.

The pools are deliberately wide: a district's staff room, not one country's.
"""

from __future__ import annotations

from jeve.core.seed import derive_rng

FIRST: tuple[str, ...] = (
    "Aarav", "Abebe", "Adaeze", "Adriana", "Ahmed", "Aiko", "Aisling", "Akira",
    "Alejandro", "Amara", "Amir", "Anaïs", "Anders", "Anika", "Anton", "Arjun",
    "Asha", "Astrid", "Ayla", "Bao", "Beatriz", "Benedikt", "Bjorn", "Bram",
    "Callum", "Camila", "Carmen", "Cecilia", "Chiara", "Chidi", "Cleo", "Dana",
    "Daniela", "Dara", "Darius", "Denny", "Dev", "Dimitri", "Dorota", "Eamon",
    "Eitan", "Elena", "Elif", "Emeka", "Emil", "Esther", "Farah", "Fatima",
    "Felix", "Fiona", "Freya", "Gabriel", "Grace", "Greta", "Hamid", "Hana",
    "Hiro", "Hugo", "Ida", "Imani", "Ines", "Ingrid", "Isak", "Ivo", "Jamal",
    "Jana", "Jasper", "Joaquin", "Jonas", "Julian", "Kai", "Kalinda", "Karim",
    "Katya", "Kenji", "Kirsten", "Kwame", "Lars", "Leila", "Lena", "Leon",
    "Lila", "Linnea", "Lior", "Lucia", "Luka", "Maeve", "Malik", "Mara",
    "Marcus", "Mariam", "Marta", "Mateo", "Mei", "Mikel", "Milo", "Mira",
    "Nadia", "Naomi", "Nikolai", "Nilufar", "Noor", "Olamide", "Olga", "Omar",
    "Oscar", "Owen", "Paloma", "Petra", "Priya", "Rafael", "Rania", "Rasmus",
    "Ravi", "Rhiannon", "Rosa", "Ruth", "Saba", "Samir", "Sara", "Sebastian",
    "Selin", "Sigrid", "Simone", "Siobhan", "Sofia", "Soren", "Suki", "Tariq",
    "Tessa", "Theo", "Tomas", "Tova", "Ulla", "Uma", "Valentina", "Vera",
    "Viktor", "Wanjiru", "Wen", "Xavier", "Yara", "Yusuf", "Zara", "Zoltan",
)  # fmt: skip

LAST: tuple[str, ...] = (
    "Aaltonen", "Abara", "Adeyemi", "Ahmadi", "Almeida", "Andrade", "Antonov",
    "Baptiste", "Bergström", "Bianchi", "Boateng", "Brandt", "Castellanos",
    "Chen", "Cohen", "Dalgaard", "Delgado", "Diallo", "Dubois", "Eriksen",
    "Etxeberria", "Farrow", "Fischer", "Fontaine", "Gallagher", "Garza",
    "Halvorsen", "Haddad", "Hoffmann", "Ibarra", "Ishikawa", "Iversen",
    "Jansen", "Jovanović", "Kaplan", "Karlsson", "Kowalczyk", "Kimura",
    "Laurent", "Lindqvist", "Lombardi", "Mbeki", "Marchetti", "Mensah",
    "Moreau", "Nakamura", "Ndlovu", "Nieminen", "Novak", "Okafor", "Okonkwo",
    "Olsen", "Ortega", "Osei", "Park", "Petrov", "Quintero", "Raghunathan",
    "Reyes", "Rahman", "Rossi", "Saito", "Schneider", "Sharma", "Solberg",
    "Svensson", "Tanaka", "Toure", "Trethewey", "Vanterpool", "Varga",
    "Vieira", "Volkov", "Walsh", "Weber", "Yilmaz", "Zhang", "Zielinski",
    "Abernathy", "Ackerley", "Bassett", "Calloway", "Dunmore", "Ellery",
    "Fairbanks", "Goodwin", "Hartley", "Ingram", "Jessop", "Kendrick",
    "Lockwood", "Mallory", "Norwood", "Pemberly", "Radcliffe", "Sutherland",
    "Thornbury", "Underhill", "Wetherby", "Yeardley",
)  # fmt: skip


def person_name(root_seed: int, person_id: str) -> str:
    """A first and last name for one person, from their id alone."""

    rng = derive_rng(root_seed, "name", person_id)
    first = FIRST[int(rng.random() * len(FIRST))]
    last = LAST[int(rng.random() * len(LAST))]
    return f"{first} {last}"
