// Imported first by main.tsx: ES modules evaluate in import order, and schemas defined at import
// time would otherwise trigger zod's `new Function` probe before this runs. The CSP forbids
// eval, so the probe only ever fails — and the browser reports the violation.
import { z } from "zod";

z.config({ jitless: true });
