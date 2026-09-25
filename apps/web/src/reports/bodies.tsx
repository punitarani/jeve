import type { ComponentType } from "react";
import { Day1InProd } from "./day-1-in-prod/Day1InProd";
import { Day3InProd } from "./day-3-in-prod/Day3InProd";

/** Each published report's page body, by slug. Kept apart from `index.ts` so
 * listing the reports does not pull every report's data into the bundle. */
export const BODIES: Record<string, ComponentType> = {
	"day-3-in-prod": Day3InProd,
	"day-1-in-prod": Day1InProd,
};
