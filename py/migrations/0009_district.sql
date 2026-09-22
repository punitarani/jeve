-- CORE-0012 / WORLD-0006: a district of storeys.
--
-- Twelve firms of any kind, teams that work on floors, products that belong
-- to a vendor, and a position that has a floor. The vocabulary that used to be
-- a CHECK constraint lives in `jeve.core.orgs` now, which is the one place a
-- firm is described; a constraint here would be a second copy of it.

ALTER TABLE orgs DROP CONSTRAINT orgs_kind_check;
ALTER TABLE orgs ADD COLUMN archetype text NOT NULL DEFAULT 'professional_services';
ALTER TABLE orgs ALTER COLUMN archetype DROP DEFAULT;

CREATE TABLE teams (
    id              text PRIMARY KEY,           -- org.team
    org_id          text        NOT NULL REFERENCES orgs(id),
    name            text        NOT NULL,
    floor           integer     NOT NULL CHECK (floor >= 0),
    layout          text        NOT NULL,
    ord             integer     NOT NULL         -- seating order within the org
);
CREATE INDEX teams_org ON teams (org_id, floor, ord);

ALTER TABLE persons ADD COLUMN team_id text REFERENCES teams(id);
CREATE INDEX persons_team ON persons (team_id);

-- A product belongs to the vendor that sells it and is *for* something; a
-- customer's dependency is on the category, whoever sells it.
ALTER TABLE modules ADD COLUMN org_id text REFERENCES orgs(id);
ALTER TABLE modules ADD COLUMN category text;
UPDATE modules SET org_id = 'tallybird', category = id WHERE org_id IS NULL;
ALTER TABLE modules ALTER COLUMN org_id SET NOT NULL;
ALTER TABLE modules ALTER COLUMN category SET NOT NULL;
ALTER TABLE modules ADD CONSTRAINT modules_category_check
    CHECK (category IN ('timetrack', 'invoicing', 'pos'));

-- A zone is a building (its firm's id), the plaza, or home. The floor is
-- which storey of the building; 0 outdoors and at home.
ALTER TABLE positions DROP CONSTRAINT positions_zone_check;
ALTER TABLE positions ADD CONSTRAINT positions_zone_check CHECK (zone <> '');
ALTER TABLE positions ADD COLUMN floor integer NOT NULL DEFAULT 0 CHECK (floor >= 0);
ALTER TABLE positions ADD CONSTRAINT positions_floor_home CHECK (zone <> 'home' OR floor = 0);

-- Every firm with a till, not only the cafe.
ALTER TABLE cafe_sales RENAME TO retail_sales;
ALTER TABLE retail_sales ADD COLUMN org_id text REFERENCES orgs(id);
UPDATE retail_sales SET org_id = 'thirdrail' WHERE org_id IS NULL;
ALTER TABLE retail_sales ALTER COLUMN org_id SET NOT NULL;
ALTER INDEX cafe_sales_time RENAME TO retail_sales_time;
CREATE INDEX retail_sales_org ON retail_sales (org_id, sim_time);
