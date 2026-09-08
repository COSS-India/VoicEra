export const AGENT_NAME_MAX_LENGTH = 65;

export const LANGS = [
  "Hindi",
  "Kannada",
  "Tamil",
  "Telugu",
  "Marathi",
  "Bengali",
  "Malayalam",
  "Odia",
  "Punjabi",
  "Gujarati",
  "Assamese",
  "English (India)",
];

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export const LLM_PROVIDERS: { id: string; label: string; note: string; models: SelectOption[] }[] = [
  {
    id: "openai",
    label: "OpenAI",
    note: "Strong general reasoning, widest tool support.",
    models: [
      { value: "gpt-4o", label: "gpt-4o" },
      { value: "gpt-4o-mini", label: "gpt-4o-mini" },
      { value: "gpt-4-turbo", label: "gpt-4-turbo" },
      { value: "gpt-3.5-turbo", label: "gpt-3.5-turbo" },
    ],
  },
  {
    id: "qwen",
    label: "Qwen",
    note: "Competitive cost-to-quality, good multilingual base.",
    models: [
      { value: "qwen2.5-72b", label: "qwen2.5-72b" },
      { value: "qwen2.5-14b", label: "qwen2.5-14b" },
    ],
  },
  {
    id: "kenpath",
    label: "Kenpath",
    note: "Tuned specifically on Indic call-center transcripts.",
    models: [{ value: "kenpath-indic-1", label: "kenpath-indic-1" }],
  },
  {
    id: "custom",
    label: "Custom LLM",
    note: "Bring your own hosted endpoint.",
    models: [{ value: "gemma-4-26b-it", label: "google/gemma-4-26B-it" }],
  },
  {
    id: "azure",
    label: "Azure OpenAI",
    note: "Not integrated yet.",
    models: [{ value: "azure-na", label: "Not available", disabled: true }],
  },
  {
    id: "anthropic",
    label: "Anthropic",
    note: "Not integrated yet.",
    models: [{ value: "anthropic-na", label: "Not available", disabled: true }],
  },
];

export const STT_PROVIDERS: {
  id: string;
  label: string;
  indicOnly?: boolean;
  note: string;
  models: SelectOption[];
}[] = [
  {
    id: "ai4bharat",
    label: "AI4Bharat",
    indicOnly: true,
    note: "Open models from IIT Madras — self-hostable, strong on Indic accents.",
    models: [{ value: "indic-conformer-stt", label: "indic-conformer-stt" }],
  },
  {
    id: "bhashini",
    label: "Bhashini",
    indicOnly: true,
    note: "Government of India's public language stack.",
    models: [{ value: "bhashini-asr-v2", label: "bhashini-asr-v2" }],
  },
  {
    id: "sarvam",
    label: "Sarvam",
    note: "Balanced latency and accuracy across Indic + English.",
    models: [{ value: "saarika-v2", label: "saarika-v2" }],
  },
  {
    id: "deepgram",
    label: "Deepgram",
    note: "Fastest transcription here, but weaker on Indic accents.",
    models: [{ value: "nova-2", label: "nova-2" }],
  },
  {
    id: "elevenlabs",
    label: "ElevenLabs",
    note: "High accuracy, English-first.",
    models: [{ value: "scribe-v1", label: "scribe-v1" }],
  },
];

export interface VoiceOption {
  id: string;
  name: string;
  note: string;
}

export const TTS_PROVIDERS: {
  id: string;
  label: string;
  indicOnly?: boolean;
  note: string;
  model: string;
  voices: VoiceOption[];
}[] = [
  {
    id: "ai4bharat",
    label: "AI4Bharat",
    indicOnly: true,
    note: "Open, self-hostable Indic voices.",
    model: "indic-parler-tts",
    voices: [
      { id: "rohit", name: "Rohit", note: "Warm, unhurried. Advisory calls." },
      { id: "divya", name: "Divya", note: "Clear and brisk. Status lookups." },
      { id: "aman", name: "Aman", note: "Neutral, formal register." },
      { id: "rani", name: "Rani", note: "Gentle, patient with elderly callers." },
    ],
  },
  {
    id: "bhashini",
    label: "Bhashini",
    indicOnly: true,
    note: "Public-sector Indic voice stack.",
    model: "bhashini-tts-v2",
    voices: [
      { id: "meera", name: "Meera", note: "Standard government-line tone." },
      { id: "arjun", name: "Arjun", note: "Slightly more energetic delivery." },
    ],
  },
  {
    id: "sarvam",
    label: "Sarvam",
    note: "Natural code-switching between Indic and English.",
    model: "bulbul-v2",
    voices: [
      { id: "anushka", name: "Anushka", note: "Friendly, everyday register." },
      { id: "karun", name: "Karun", note: "Deeper, reassuring tone." },
    ],
  },
  {
    id: "cartesia",
    label: "Cartesia",
    note: "Lowest latency TTS in this list.",
    model: "sonic-2",
    voices: [
      { id: "asha", name: "Asha", note: "Fast, crisp — good for short broadcasts." },
      { id: "vikram", name: "Vikram", note: "Confident, brand-forward tone." },
    ],
  },
  {
    id: "elevenlabs",
    label: "ElevenLabs",
    note: "Highest expressiveness, English-first.",
    model: "eleven-turbo-v2-5",
    voices: [
      { id: "priya", name: "Priya", note: "Expressive, best for English-heavy lines." },
      { id: "dev", name: "Dev", note: "Grounded, calm narrator tone." },
    ],
  },
];

export const TIPS: Record<string, string> = {
  name: "Shown internally and in call logs — callers never hear it.",
  welcome: "The very first line the caller hears. Keep it under two commas or the voice tends to stutter on the pauses.",
  prompt: "This is read before every reply. Keep instructions concrete — \"never guess\" beats \"be careful.\"",
  llmProvider: "Changing this resets the model choice below to that provider's default.",
  tokens: "Roughly how long a single reply can run. Lower this for tighter, faster answers.",
  temp: "Higher values make the agent's phrasing less predictable call to call.",
  kb: "When on, the agent quotes from the documents you attach instead of guessing.",
  langs: "The first language opens the call. Callers who switch mid-call are followed automatically.",
  voice: "Preview a voice before committing — it's easy to change later, but callers notice a swap.",
  sttProvider: "Indic-only providers won't appear as options once you pick English as a language.",
  ttsProvider: "This also determines which voices are available.",
  buffer: "Lower buffers feel snappier but risk clipping the caller's first word on a slow line.",
  interrupt: "How many words the caller needs to say before the agent stops talking and listens.",
  online: "Every 90 seconds of silence, the agent gently checks the line is still connected.",
  silence: "If the caller goes quiet this long, the agent politely ends the call.",
  timeout: "A hard ceiling so no single call runs away with cost or a support agent's afternoon.",
  holds: "Said while the agent is thinking on a slow lookup, so the line doesn't feel dead.",
  holdTimeout: "How long the agent waits after starting to think before playing a hold message.",
  onlineMessage: "What the agent says when checking whether the caller is still on the line.",
  onlineSeconds: "Seconds of silence after the agent speaks before it checks the caller is still there.",
  onlineRepeats: "How many times the agent repeats the check before giving up and ending the call.",
  onlineClosing: "Said right before hanging up, after the last unanswered check.",
  autoEnding: "Lets the agent end the call itself once it detects the conversation is done.",
  autoEndingGraceful: "Says a closing line and waits a beat before hanging up, instead of ending abruptly.",
};

export interface AgentForm {
  name: string;
  purpose: string;
  welcome: string;
  ignoreGreetingSpeech: boolean;
  prompt: string;
  /** Default values for `{{var}}` tokens referenced in `prompt` — sent as the
   * agent's `custom_variables`, overridable per call. */
  customVariables: Record<string, string>;
  llmProvider: string;
  llmModel: string;
  /** Values picked for the selected LLM model's own extra fields (temperature,
   * max_tokens, base_url, …) — keyed by field name, shape varies per model. */
  llmExtra: Record<string, unknown>;
  kbEnabled: boolean;
  kbDocs: string[];
  langs: string[];
  ttsProvider: string;
  ttsModel: string;
  voice: string;
  /** Values picked for the selected TTS model's own extra fields (speed, volume, …), excluding voice. */
  ttsExtra: Record<string, unknown>;
  sttProvider: string;
  sttModel: string;
  /** Values picked for the selected STT model's own extra fields (base_url, …). */
  sttExtra: Record<string, unknown>;
  bufferMs: number;
  delivery: string;
  interruptThreshold: number;
  checkStillThere: boolean;
  silenceTimeout: number;
  callLimit: number;
  holdPhrases: string[];
  holdMessageTimeoutSeconds: number;
  onlineDetectionMessage: string;
  onlineDetectionSeconds: number;
  onlineDetectionRepeats: number;
  onlineDetectionClosingMessage: string;
  autoCallEndingEnabled: boolean;
  autoCallEndingGraceful: boolean;
}

export const DEFAULT_FORM: AgentForm = {
  name: "",
  purpose: "",
  welcome: "Namaste, VoicEra se bol raha hoon",
  ignoreGreetingSpeech: true,
  prompt:
    "You are a helpful agent. You help the caller with their questions. Never speak more than two sentences. Keep your answers concise.",
  customVariables: {},
  llmProvider: "",
  llmModel: "",
  llmExtra: {},
  kbEnabled: false,
  kbDocs: [],
  langs: ["hi"],
  ttsProvider: "",
  ttsModel: "",
  voice: "",
  ttsExtra: {},
  sttProvider: "",
  sttModel: "",
  sttExtra: {},
  bufferMs: 50,
  delivery: "",
  interruptThreshold: 3,
  checkStillThere: true,
  silenceTimeout: 30,
  callLimit: 600,
  holdPhrases: ["Ek minute dekh raha hoon"],
  holdMessageTimeoutSeconds: 5,
  onlineDetectionMessage: "Are you still there?",
  onlineDetectionSeconds: 90,
  onlineDetectionRepeats: 1,
  onlineDetectionClosingMessage: "I'll end the call now. Goodbye.",
  autoCallEndingEnabled: false,
  autoCallEndingGraceful: false,
};

export const TPL_CATS = [
  "All",
  "Agriculture",
  "Welfare",
  "Governance",
  "Education",
  "Reminders",
  "Surveys",
  "Health",
  "Starters",
];

export interface AgentTemplate {
  id: string;
  name: string;
  category: string;
  by: string;
  lang: string;
  line: string;
  note: string;
  set: Partial<AgentForm>;
}

export const TEMPLATES: AgentTemplate[] = [
  {
    id: "mandi-rate",
    name: "Mandi rate advisory",
    category: "Agriculture",
    by: "VoicEra",
    lang: "Kannada",
    line: "ಇಂದಿನ ಟೊಮೇಟೊ ಮಂಡಿ ದರ ಎಷ್ಟು?",
    note: "Crop-price lookup plus a short weather outlook for the caller's district.",
    set: {
      name: "Mandi Rate Advisory",
      purpose: "Tells farmers today's crop prices and a short weather outlook.",
      welcome: "Namaskara, mandi dara mahiti kelalu koogi.",
      langs: ["kn", "hi"],
      prompt:
        "You give today's mandi price for the crop the caller names, then a one-line weather outlook for their district. Never guess a price you don't have.",
    },
  },
  {
    id: "pension-status",
    name: "Pension status check",
    category: "Welfare",
    by: "Govt of Tamil Nadu",
    lang: "Tamil",
    line: "எனது ஓய்வூதியம் இன்னும் வரவில்லை.",
    note: "Looks up an application's status by the caller's registered number.",
    set: {
      name: "Pension Status",
      purpose: "Checks pension application and disbursal status.",
      langs: ["ta", "te"],
      prompt:
        "You confirm the caller's registered phone number, then read back their pension application status plainly. If it is pending, give the expected date.",
    },
  },
  {
    id: "grievance-intake",
    name: "Grievance intake",
    category: "Governance",
    by: "VoicEra",
    lang: "Hindi",
    line: "मेरी शिकायत दर्ज करनी है।",
    note: "Logs a complaint and reads back a ticket number for follow-up.",
    set: {
      name: "Grievance Intake",
      purpose: "Logs a complaint and issues a ticket number.",
      langs: ["hi"],
      prompt:
        "You collect the caller's complaint in their own words, summarise it back for confirmation, then issue a ticket number and expected response time.",
    },
  },
  {
    id: "scholarship-eligibility",
    name: "Scholarship eligibility",
    category: "Education",
    by: "IIIT-B",
    lang: "Kannada",
    line: "ನಾನು ವಿದ್ಯಾರ್ಥಿವೇತನಕ್ಕೆ ಅರ್ಹನೇ?",
    note: "FAQ-grounded eligibility answers pulled from the scholarship handbook.",
    set: {
      name: "Scholarship Eligibility",
      purpose: "Answers eligibility questions from the scholarship handbook.",
      langs: ["kn", "en"],
      kbEnabled: true,
      prompt:
        "Answer eligibility questions only from the attached scholarship handbook. If it isn't covered there, say so and give the helpline number.",
    },
  },
  {
    id: "appointment-confirmation",
    name: "Appointment confirmation",
    category: "Reminders",
    by: "VoicEra",
    lang: "Hindi",
    line: "आपकी अपॉइंटमेंट कल सुबह 10 बजे है।",
    note: "Confirms, reschedules, or cancels an upcoming appointment.",
    set: {
      name: "Appointment Confirmation",
      purpose: "Confirms, reschedules, or cancels an appointment.",
      langs: ["hi"],
      prompt:
        "State the appointment date and time, then ask the caller to confirm, reschedule, or cancel. Keep the call under a minute.",
    },
  },
  {
    id: "feedback-survey",
    name: "Post-visit feedback survey",
    category: "Surveys",
    by: "COSS India",
    lang: "Telugu",
    line: "మీ సందర్శన ఎలా ఉంది?",
    note: "A short two-question rating survey after a clinic or office visit.",
    set: {
      name: "Post-visit Feedback Survey",
      purpose: "Runs a two-question satisfaction survey after a visit.",
      langs: ["te"],
      prompt:
        "Ask exactly two questions: a 1-5 satisfaction rating, then one open follow-up. Thank the caller and end the call.",
    },
  },
  {
    id: "ration-card-status",
    name: "Ration card status",
    category: "Welfare",
    by: "Govt of Odisha",
    lang: "Odia",
    line: "ମୋର ରାସନ କାର୍ଡ ଆସିଛି କି?",
    note: "Status lookup tuned for elderly callers, with extra patience built in.",
    set: {
      name: "Ration Card Status",
      purpose: "Checks ration card application status, elderly-caller tuned.",
      langs: ["or", "hi"],
      silenceTimeout: 45,
      prompt:
        "Speak slowly and repeat the status once before moving on. Never rush a caller who pauses.",
    },
  },
  {
    id: "vaccination-followup",
    name: "Vaccination follow-up",
    category: "Health",
    by: "Community Health Network",
    lang: "Hindi",
    line: "आपकी दूसरी खुराक अभी बाकी है।",
    note: "Reminds about a second dose and offers to book the next available slot.",
    set: {
      name: "Vaccination Follow-up",
      purpose: "Reminds about a second dose and books the next slot.",
      langs: ["hi"],
      prompt:
        "Remind the caller their second dose is due, then offer the next three available slots at their nearest centre.",
    },
  },
  {
    id: "blank-agent",
    name: "Blank agent",
    category: "Starters",
    by: "VoicEra",
    lang: "Hindi",
    line: "—",
    note: "Empty defaults only — a clean starting point.",
    set: {},
  },
];

export interface TestTurn {
  speaker: "agent" | "caller";
  text: string;
  gloss?: string;
}

export const TEST_SCRIPT: TestTurn[] = [
  { speaker: "agent", text: "Namaste, VoicEra se bol raha hoon. Main aapki kaise madad kar sakta hoon?", gloss: "Hello, this is VoicEra. How can I help you?" },
  { speaker: "caller", text: "आज का मंडी भाव क्या है?", gloss: "What is today's mandi rate?" },
  { speaker: "agent", text: "Answers from your instructions, and any attached documents.", gloss: "" },
  { speaker: "caller", text: "ठीक है, धन्यवाद।", gloss: "Okay, thank you." },
  { speaker: "agent", text: "Aapka din shubh ho. Call ends politely.", gloss: "Have a good day." },
];
