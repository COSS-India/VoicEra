export interface Agent {
  id: string;
  name: string;
  purpose: string;
  status: "Live" | "Draft" | "Template";
  langs: string[];
  number: string;
  score: string;
  reasoning: string;
  hearing: string;
  speaking: string;
}

const REASONING = ["gpt-4o", "gpt-4o-mini", "qwen2.5-72b", "kenpath-indic-1", "gemma-4-26B"];
const HEARING = ["AI4Bharat", "Bhashini", "Sarvam", "Deepgram", "ElevenLabs"];
const SPEAKING = ["AI4Bharat", "Bhashini", "Sarvam", "Cartesia", "ElevenLabs"];

function meta(i: number) {
  return {
    reasoning: REASONING[i % REASONING.length],
    hearing: HEARING[i % HEARING.length],
    speaking: SPEAKING[i % SPEAKING.length],
  };
}

const AGENT_SEED: Omit<Agent, "reasoning" | "hearing" | "speaking">[] = [
  { id: "a1", name: "Kisan Sahayak", purpose: "Mandi rates and crop advisory for farmers.", status: "Live", langs: ["Hindi", "Kannada", "Marathi"], number: "+91 80 6548 0891", score: "94%" },
  { id: "a2", name: "Pension Status", purpose: "Checks pension application and disbursal status.", status: "Live", langs: ["Tamil", "Telugu"], number: "+91 44 2917 3320", score: "92%" },
  { id: "a3", name: "Water Tanker Booking", purpose: "Books an emergency water tanker for a ward.", status: "Draft", langs: ["Telugu"], number: "Not linked", score: "—" },
  { id: "a4", name: "Fisheries Advisory", purpose: "Weather and catch advisory for coastal fishers.", status: "Live", langs: ["Malayalam", "Tamil"], number: "+91 484 220 5581", score: "88%" },
  { id: "a5", name: "Grievance Intake", purpose: "Logs a civic complaint and reads back a ticket number.", status: "Live", langs: ["Hindi"], number: "+91 11 4938 2201", score: "90%" },
  { id: "a6", name: "Scholarship Eligibility", purpose: "Answers scholarship FAQ from the scheme document.", status: "Live", langs: ["Kannada", "English (India)"], number: "+91 80 4092 7761", score: "87%" },
  { id: "a7", name: "Appointment Confirmation", purpose: "Confirms, reschedules, or cancels a clinic appointment.", status: "Live", langs: ["Hindi", "Punjabi"], number: "+91 172 660 4419", score: "95%" },
  { id: "a8", name: "Post-visit Feedback", purpose: "Two-question satisfaction survey after a hospital visit.", status: "Live", langs: ["Telugu"], number: "+91 40 3312 9087", score: "83%" },
  { id: "a9", name: "Ration Card Status", purpose: "Elderly-tuned ration card status lookup.", status: "Live", langs: ["Odia"], number: "+91 674 239 5510", score: "91%" },
  { id: "a10", name: "Vaccination Follow-up", purpose: "Second-dose reminder and slot booking.", status: "Live", langs: ["Hindi", "Bengali"], number: "+91 33 4021 8843", score: "89%" },
  { id: "a11", name: "Loan EMI Reminder", purpose: "Gentle EMI due-date reminder with a pay-by link.", status: "Draft", langs: ["Marathi"], number: "Not linked", score: "—" },
  { id: "a12", name: "School Admission Helpdesk", purpose: "Answers admission-window and document questions.", status: "Live", langs: ["Kannada", "Hindi"], number: "+91 80 2223 9910", score: "86%" },
];

export const AGENTS: Agent[] = AGENT_SEED.map((a, i) => ({ ...a, ...meta(i) }));

const TEMPLATE_SEED: Omit<Agent, "status" | "reasoning" | "hearing" | "speaking">[] = [
  { id: "t1", name: "Mandi rate advisory", purpose: "Crop-price lookup with a weather note.", langs: ["Kannada"], number: "Reusable", score: "—" },
  { id: "t2", name: "Pension status check", purpose: "Application-status lookup.", langs: ["Tamil"], number: "Reusable", score: "—" },
  { id: "t3", name: "Grievance intake", purpose: "Complaint logging with a ticket number.", langs: ["Hindi"], number: "Reusable", score: "—" },
  { id: "t4", name: "Scholarship eligibility", purpose: "FAQ-grounded eligibility Q&A.", langs: ["Kannada"], number: "Reusable", score: "—" },
  { id: "t5", name: "Appointment confirmation", purpose: "Confirm, reschedule, or cancel.", langs: ["Hindi"], number: "Reusable", score: "—" },
  { id: "t6", name: "Post-visit feedback survey", purpose: "Two-question rating survey.", langs: ["Telugu"], number: "Reusable", score: "—" },
  { id: "t7", name: "Ration card status", purpose: "Elderly-tuned status lookup.", langs: ["Odia"], number: "Reusable", score: "—" },
  { id: "t8", name: "Vaccination follow-up", purpose: "Second-dose reminder and booking.", langs: ["Hindi"], number: "Reusable", score: "—" },
  { id: "t9", name: "Blank agent", purpose: "Empty defaults only — start writing from scratch.", langs: ["Hindi"], number: "Reusable", score: "—" },
];

export const TEMPLATE_AGENTS: Agent[] = TEMPLATE_SEED.map((a, i) => ({
  ...a,
  status: "Template",
  ...meta(i),
}));

export const METRICS = [
  { key: "calls", label: "Calls today", value: "4,182", delta: "+8%" },
  { key: "live", label: "Agents live", value: "12", delta: "+2" },
  { key: "langs", label: "Languages served", value: "11", delta: "+1" },
  { key: "reply", label: "Median reply", value: "1.9s", delta: "−0.2s" },
];

export interface KbDoc {
  id: string;
  name: string;
  kind: string;
  state: "Indexed" | "Indexing" | "Failed";
  size: string;
  chunks: number;
  lang: string;
  usedBy: string;
  when: string;
}

export const DOCS: KbDoc[] = [
  { id: "d1", name: "Mandi_rates_Aug2026.pdf", kind: "PDF", state: "Indexed", size: "1.2 MB", chunks: 412, lang: "Kannada", usedBy: "6 agents", when: "2 days ago" },
  { id: "d2", name: "Pension_scheme_FAQ.docx", kind: "DOCX", state: "Indexed", size: "480 KB", chunks: 156, lang: "Tamil", usedBy: "2 agents", when: "1 week ago" },
  { id: "d3", name: "Grievance_categories.csv", kind: "CSV", state: "Indexed", size: "88 KB", chunks: 64, lang: "Hindi", usedBy: "1 agent", when: "3 weeks ago" },
  { id: "d4", name: "Scholarship_eligibility_2026.pdf", kind: "PDF", state: "Indexing", size: "2.1 MB", chunks: 0, lang: "Kannada", usedBy: "1 agent", when: "just now" },
  { id: "d5", name: "Vaccination_schedule.csv", kind: "CSV", state: "Failed", size: "44 KB", chunks: 0, lang: "Hindi", usedBy: "0 agents", when: "4 days ago" },
  { id: "d6", name: "Ration_card_process.pdf", kind: "PDF", state: "Indexed", size: "760 KB", chunks: 203, lang: "Odia", usedBy: "1 agent", when: "2 weeks ago" },
  { id: "d7", name: "Fisheries_advisory_notes.txt", kind: "TXT", state: "Indexed", size: "12 KB", chunks: 9, lang: "Malayalam", usedBy: "1 agent", when: "5 days ago" },
  { id: "d8", name: "Admission_window_2026.xlsx", kind: "XLSX", state: "Indexed", size: "310 KB", chunks: 71, lang: "Kannada", usedBy: "1 agent", when: "6 days ago" },
];

export interface LangGeo {
  lang: string;
  where: string;
  pct: number;
  note: string;
  x: number;
  y: number;
}

// x/y are 0-100 approximate positions within an India-shaped bounding box,
// used to place markers without requiring a full state-boundary basemap.
export const LANGS_GEO: LangGeo[] = [
  { lang: "Hindi", where: "UP · Bihar · MP · Rajasthan", pct: 21, note: "The largest single share — mostly north and central India.", x: 48, y: 34 },
  { lang: "Kannada", where: "Karnataka", pct: 17, note: "Belagavi callers code-mix Marathi; the agent switches mid-call rather than asking them to repeat.", x: 44, y: 66 },
  { lang: "Tamil", where: "Tamil Nadu · Puducherry", pct: 14, note: "Formal register expected on government lines.", x: 50, y: 82 },
  { lang: "Telugu", where: "Andhra Pradesh · Telangana", pct: 12, note: "Coastal and Rayalaseema callers use distinct vocabulary for the same terms.", x: 54, y: 62 },
  { lang: "Marathi", where: "Maharashtra", pct: 9, note: "Mumbai callers often open in English, then switch.", x: 38, y: 52 },
  { lang: "Bengali", where: "West Bengal", pct: 8, note: "Rural callers prefer a slower pace on numeric readbacks.", x: 74, y: 40 },
  { lang: "Odia", where: "Odisha", pct: 6, note: "Elderly callers benefit from longer silence tolerance before hangup.", x: 64, y: 50 },
  { lang: "Malayalam", where: "Kerala", pct: 5, note: "Highest literacy — callers often skip the intro and go straight to the ask.", x: 40, y: 88 },
  { lang: "Gujarati", where: "Gujarat", pct: 4, note: "Business-hours calls dominate; low volume overnight.", x: 28, y: 42 },
  { lang: "Punjabi", where: "Punjab · Haryana", pct: 3, note: "Frequent code-mixing with Hindi.", x: 40, y: 20 },
  { lang: "Assamese", where: "Assam", pct: 1, note: "Smallest volume, but highest completion rate.", x: 82, y: 28 },
];

export const langTotal = "26,914";
