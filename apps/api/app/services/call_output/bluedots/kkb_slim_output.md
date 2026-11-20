Analyse the call transcript and extract the following information. 
If a value is not present, use "NA" for strings, [] for arrays, or 0 for counts.

1. seeker_name — The seeker's name as registered in the contact upload list. 
   Pulled from the input CSV at call initiation. Falls back to "Unknown" if not provided.

2. call_answered — Was the call picked up? 
   Values: "Yes" if the seeker spoke at all, "No" if the call went unanswered or 
   dropped before any user turn.

3. call_engaged — Did the seeker meaningfully engage in the conversation, beyond a 
   one-word reply? 
   Values: "Yes" if the user had three or more substantive turns, "No" otherwise.

4. primary_topic — What was the main subject of the call? 
   Values: "Job search" if the conversation centred on finding work, 
   "Profile update" if the seeker mainly shared/updated profile info, 
   "No engagement" if the call did not progress past greeting.

5. user_intent — What was the user's underlying intent? 
   Values: "Job Application" if they applied, "Job Search" if they explored jobs, 
   "Profile Update" if they only shared profile info, "General" for unclear engaged 
   callers, "NA" for no engagement.

6. jobs_shown — Did the bot present any jobs to the seeker during the call? 
   Values: "Yes" / "No".

7. jobs_recommended — All jobs the bot surfaced to the seeker during the call, 
   in the order they were shown. Array of objects.
   Each object: { job_id, role, company_name, company_location, salary_offered, 
                  qualification_required }

8. applied_to_job — Was at least one job application successfully submitted on 
   this call? 
   Values: "Yes" if any apply_job tool call succeeded, "No" otherwise.

9. applications_count — How many jobs were successfully applied to in this call? 
   Integer; 0 if none.

10. jobs_applied — Jobs the seeker successfully applied to (apply_job tool call 
    succeeded). Array of objects.
    Each object: { job_id, role, company_name, company_location, salary_offered, 
                   qualification_required }

11. jobs_failed_to_apply — Jobs the seeker tried to apply to but the apply_job 
    tool call failed (e.g. HTTP 404, profile not found, system error). 
    Array of objects.
    Each object: { job_id, role, company_name, company_location, salary_offered, 
                   qualification_required, failure_reason }

12. drop_reason — If the seeker dropped off or disengaged from the call before 
    natural completion, what was the behavioral reason? 
    This captures SEEKER behavior, not technical failures. 
    Examples: "Said not looking", "Asked to call later", "Language barrier", 
    "Hung up mid-call", "Already employed", "Frustrated with repeated apply failures". 
    NA if the call completed normally.

12a. call_later_request: Did the CALLER ask to be called back later ("बाद में कॉल करना", "अभी busy हूँ",
    "ನಂತರ ಕಾಲ್ ಮಾಡಿ")? "Yes: <the time they named, in English, or 'no time given'>" or "NA".
    Only the caller's own request counts; a bot promise is never a call-later request.
    The value is TEXT in exactly one of these shapes: "Yes: evening", "Yes: tomorrow morning",
    "Yes: no time given", or "NA". Never a date, a clock time you did not hear, or a timestamp: the
    call's own time is not the callback time.

13. final_summary — A 2-3 sentence factual summary of the call in English. 
    Cover: (1) whether the seeker was interested in jobs, (2) what role/location/
    salary they discussed, (3) whether they applied or tried to apply. 
    No opinions, no speculation.

14. ready_for_interview — Did the seeker indicate they could attend an interview 
    if an employer shortlists them (a single question asked once before applying)? 
    Values: "Yes" if they said they can attend (including a phone interview), 
    "No" if they said they cannot, "Conditional" if it depends (only by phone, 
    only if nearby, only at certain times), "NA" if the question was not asked 
    (e.g. no application was attempted) or the seeker gave no clear answer.

15. consent_status — On the new-caller path (new_seeker="yes"), did the caller give the consent needed to create their profile and apply?
   Values: "Given" if the caller agreed at the consent gate and create_profile was called; "Declined" if the caller refused consent (no create_profile, no apply_job — call ended at the consent gate); "NA" for a returning caller (already consented) or if the consent gate was never reached. Default "NA".

15a. preferred_location — Did the caller state a place they want to work, when the jobs
    on offer did not suit them (the mismatch preference capture), or when they corrected
    the location the call opened with? Extract the place in the caller's own terms, in
    English/Latin script — a city, a locality, or a station/landmark if that is all they
    gave (e.g. "Vasundhara, Ghaziabad", "Noida", "near Sahibabad station").
    This is where they want to WORK. It is NOT their residence and must never be copied
    from the profile's stored location, from a job's location, or from the call's input
    location. "NA" if the caller never stated a preferred work location.
    **The test is whether the words came out of the CALLER's mouth.** If the bot named a place
    and the caller merely agreed ("हाँ", "सही"), that counts — they confirmed it aloud. If the
    place appears only in the call's input variables, only in their stored profile, or only in a
    job's details, it is "NA" no matter how obviously it looks like their location. A value that
    equals the call's input `location` and was never spoken by the caller is the single most
    common way this field goes wrong: check the caller's turns before filling it.
    A station or landmark the caller offered instead of an area is a valid value — record it as
    they said it.

15c. input_location_had_jobs — Did the call's input `location` actually have any job in
    the list the bot was given? Compare the call's input location against the `location`
    field of the jobs offered.
    Values: "Yes" if at least one job sat in that place or its city; "No" if the input
    location was a real place and NOT ONE job was there (e.g. the call opened on "Delhi"
    and every job was in Ghaziabad); "NA" if the input location was empty or a sentinel
    ("Any", "NA", "-", a pincode, campaign metadata).
    **Compare the INPUT location string to the job list. Do NOT follow what the bot talked
    about.** On call d3521a89 the input was "Delhi", every job was in Ghaziabad, and the bot
    confirmed "गाज़ियाबाद" to the caller — the correct value is "No", because the question is
    whether the place the caller was DIALLED for had any job, not which place got discussed.
    Reading it off the conversation hides exactly the targeting problem this field exists to
    surface. It went wrong the other way on call 2bf465d9: the input was "Hubli", SIX of the
    eight jobs were in Hubli, the bot happened to talk about Dharwad, and this field was
    recorded as "No". Match the input string against every job's `location` field — a job
    listed as "Keshwapur, Hubli" IS in Hubli — and ignore which city got discussed.
    This is a CAMPAIGN-TARGETING signal, not a bot verdict: "No" means the caller was
    dialled for a city we hold no inventory in, which is worth surfacing even when the
    call otherwise went perfectly. Judge it from the input location and the job list only
    — never from what the caller said they wanted.

15d. nearest_landmark — Did the caller name a nearest bus stop, railway/metro station, or
    well-known landmark near where they live? Normally the Location step's answer — BUT if later
    in the call they say they have moved or live somewhere else and name a stop or landmark near the
    NEW place, that later one REPLACES it. Always the landmark for where they live NOW.
    Extract it in the caller's own terms, transliterated to English/Latin script
    (e.g. "Nashik Road station", "near Sabzi Mandi", "Sahibabad station").
    "NA" if they were never asked (because it was already known from a previous call) or
    gave no usable answer. Never fill it from the input location, a job's location, or the
    stored profile — only from what the caller said on THIS call.
    **Their FINAL answer, exactly as for home_area.** If, later in the call, they say they have
    moved or live somewhere else and name a stop or landmark near the NEW place, record THAT one —
    not the one they gave first. The two fields must describe the same place: on call c0e479e9 the
    caller moved from Muradnagar to Modinagar mid-call, home_area correctly became "Modinagar", and
    this field kept "Muradnagar bus stand" — a landmark in one town paired with an area in another.
    If they say they moved but name no new landmark, this is "NA": the old landmark no longer
    describes where they live.
    **If the BOT supplied the landmark rather than the caller, this is "NA".** That has happened:
    on call d3521a89 the bot asked for the nearest station, the caller answered "जी बताइए"
    (a non-answer), and the bot said "साहिबाबाद स्टेशन है।" itself. Nothing was learned on that
    call, so the correct value is "NA" — recording it as though the caller gave it launders a
    bot fabrication into a stored caller fact.

15e. pin_code — The caller's 6-digit postal PIN code, as settled at the Location step's Turn C.
    Record it when the caller CONFIRMED the pin we already held, or gave one themselves — six
    digits, digits only (e.g. "110098"). "NA" if the pin was never settled: they did not know it,
    refused, were never asked, or the turn was skipped.
    **To check the length, write the confirmed pin as digit words, one per digit, and count the
    WORDS** — not the number. Six → record those six digits. Any other count → "NA". Never add, drop or
    change a digit to make it six: on call 2ad96965 the caller agreed to a five-digit read-back and it
    was recorded as "110024", with a digit invented.
    **Only what the caller confirmed or said out loud counts.** A pin sitting in the input location
    that the caller never confirmed is "NA" — the point of this field is that a human agreed to it.
    Never fill it from a job's location, the stored profile, or your own knowledge of the city, and
    never repair a value: if what was captured is not exactly six digits, this is "NA". A guessed or
    completed pin would look identical to a confirmed one and is worse than an empty field.

15b. preference_mismatch_reason — Why the caller rejected the jobs, when they did.
    Values: "Location" if they turned them down because of distance/area/city;
    "Role" if they turned them down because it was not the kind of work they want;
    "NA" if they did not reject the jobs, or applied, or gave no reason.
    Exactly one value — if they objected on both, use the one the bot actually acted on.

15f. home_area — The area, locality or town the caller LIVES in, as settled on THIS call, in
    English/Latin script (e.g. "Muradnagar", "Raj Nagar Extension", "Vaishali"). Their FINAL answer:
    if they corrected it at the Location step, or later said they had moved or live somewhere else,
    record the LATEST place they gave. Record it when the caller confirmed the area read back to
    them, or named one themselves. "NA" if it was never settled. Only what the caller confirmed or
    said out loud counts — never fill it from a job's location, and never with a city or state
    alone when they named something more specific. This is where they LIVE, not where they want to
    work: that is preferred_location.

16. services_pitched — Was a support-service offer actually spoken to the caller on this call
    (section S, wherever it fired — early because they were not looking for work, after a no-match,
    after a successful apply, or at the closing step)?
    Values: "Yes" if an offer was spoken, "No" if none was.
    NOTE: this replaces the old service_provider_pitched. The offer now NAMES a real organisation
    instead of pitching "some service providers", so an offer with no organisation named is a defect
    and should still be recorded as "Yes" (it was spoken) — service_offered will show it as "NA",
    which is how the report surfaces it.

17. service_interest — How did the caller respond to that offer? Read the CALLER's words only, never
    the agent's ("बहुत बढ़िया, हमारी टीम..." is not evidence).
    "Yes" ONLY when the caller gave an explicit yes to the offer ("पहुँचा दीजिए", "भेज दीजिए", "बिल्कुल",
      "इंटरेस्टेड हूँ"), OR gave a bare "हाँ / जी / ओके / ठीक है" and then NAMED a callback time when the
      agent asked (see 17a).
    "Maybe" when the only reply was a bare acknowledgement with no time named after it, or filler,
      noise, silence or a hang-up.
    "No" for a refusal at any point; the LAST answer wins. "NA" if no offer was made.
    Not answers: replies to the read-back or to "आप सुन रहे हैं?", "*No audio...*" / "*Unclear Speech*"
    markers, single syllables, speech to someone else.

17a. service_callback_slot — The time the CALLER named for the service team to call:
    "Morning" | "Afternoon" | "Evening" | "Anytime" | "Other: <their words in English>" | "NA".
    It must come from a caller turn; "NA" whenever the caller did not say one.

18. service_offered — WHICH service was offered, by name: the organisationName exactly as
    get_services returned it (e.g. "TRRAIN Trust", "Aastha Skill Development Centre (MoLE
    Certified)", "Model Career Centre (MCC) Ghaziabad – Govt of India", "HHH Foundation",
    "Yuva Kaushal Vikas Kendra (MoLE Certified)"). "NA" if no offer was made, or if an offer was
    spoken without naming an organisation. **Never a name the tool did not return** — an invented
    organisation here is the same class of error as an invented job.

19. service_need_matched — What need was the offer matched to?
    Values: "Training" (skilling / vocational / wants to learn a trade or get a certificate),
    "Counselling" (does not know what suits them, interview nerves, career advice),
    "Placement" (wants help actually getting placed), "Financial" (fees, schemes, financial aid),
    "Travel" (transport or accommodation), "Other", "NA" if no offer was made.

20. jobs_interest — At the introduction, did the caller say they are looking for work?
    Values: "Yes" (they want work, named a role, or asked what we have), "No" (a clear refusal —
    they are not looking for a job right now), "Unclear" (no real answer; the bot correctly treated
    it as a yes and continued). This is the top-of-funnel number: "No" callers should have gone
    straight to services and should show jobs_fetched = "No".

21. jobs_fetched — Did a job tool actually run this call?
    Values: "Recommended" if get_recommended_jobs ran (personalised, anchored on their profile),
    "Search" if get_jobs ran (query-based), "Both" if both ran, "No" if neither did.
    **Read this from the tool calls, not from the conversation.**

22. jobs_offered_count — How many DISTINCT jobs were actually named aloud to the caller across the
    whole call, as an integer (0 if none). Count jobs spoken, not rows returned by the tool — most
    returned rows are dropped as unusable before anything is said.

23. job_roles_offered — The role names actually spoken aloud, as a comma-separated list, copied from
    what was said (e.g. "Data Entry Operator, Computer Operator"). "NA" if none were named.
    **A role of "na", "Any" or anything containing "|" appearing here is a BUG** — those rows must be
    dropped before presentation, so their presence in this field means the junk filter failed.

24. job_no_match — Did the caller ask for a kind of work we could not offer?
    Values: "Yes" if, after cleaning the tool result, nothing relevant survived and the caller was
    told so; "No" if at least one relevant job was offered; "NA" if jobs were never discussed.

25. asked_job_location — Did the caller ask WHERE a job was?
    Values: "Yes" / "No". If "Yes", the bot must have said it does not have the exact location —
    it is never allowed to state or guess a job's city, because the API returns it masked. Any call
    where this is "Yes" is worth reading to confirm no city was invented.

NOTE ON CALL DIRECTION — do not try to output it. The platform does not inject a direction variable
and the model cannot know whether we dialled the caller or they dialled us. Direction is derived from
the call record instead: an inbound call carries caller_no / in_did, an outbound one carries
to_number / out_did. Any inbound-vs-outbound metric is computed there, not here.


26. EXAMPLE OUTPUT — Below is an example of how all the above fields should be 
    aggregated and returned for a single call. Use this exact structure:

{
  "seeker_name": "Rajesh Kumar",
  "call_answered": "Yes",
  "call_engaged": "Yes",
  "primary_topic": "Job search",
  "user_intent": "Job Application",
  "jobs_shown": "Yes",
  "jobs_recommended": [
    {
      "job_id": "f493b9d2-1625-48af-a20d-95e95f56fd2f",
      "role": "Electrician",
      "company_name": "Sigmatek Industrial Electronics",
      "company_location": "Modinagar, Ghaziabad",
      "salary_offered": "₹20,000–40,000",
      "qualification_required": "ITI Electrical"
    },
    {
      "job_id": "0eb6e86c-6a9e-4b37-8a1e-2d15f5573b5c",
      "role": "Machine Operator (PCB Electroplating Line)",
      "company_name": "Vishwakarma Auto Pipes",
      "company_location": "Sahibabad, Ghaziabad",
      "salary_offered": "₹15,000–18,000",
      "qualification_required": "10th pass"
    },
    {
      "job_id": "9098465107",
      "role": "Solar Energy Consultant",
      "company_name": "NA",
      "company_location": "Ghaziabad",
      "salary_offered": "₹18,000–25,000",
      "qualification_required": "Graduate"
    }
  ],
  "applied_to_job": "Yes",
  "applications_count": 2,
  "jobs_applied": [
    {
      "job_id": "f493b9d2-1625-48af-a20d-95e95f56fd2f",
      "role": "Electrician",
      "company_name": "Sigmatek Industrial Electronics",
      "company_location": "Modinagar, Ghaziabad",
      "salary_offered": "₹20,000–40,000",
      "qualification_required": "ITI Electrical"
    },
    {
      "job_id": "0eb6e86c-6a9e-4b37-8a1e-2d15f5573b5c",
      "role": "Machine Operator (PCB Electroplating Line)",
      "company_name": "Vishwakarma Auto Pipes",
      "company_location": "Sahibabad, Ghaziabad",
      "salary_offered": "₹15,000–18,000",
      "qualification_required": "10th pass"
    }
  ],
  "jobs_failed_to_apply": [
    {
      "job_id": "9098465107",
      "role": "Solar Energy Consultant",
      "company_name": "NA",
      "company_location": "Ghaziabad",
      "salary_offered": "₹18,000–25,000",
      "qualification_required": "Graduate",
      "failure_reason": "HTTP 404 — profile not found"
    }
  ],
  "ready_for_interview": "Yes",
  "consent_status": "NA",
  "preferred_location": "Vasundhara, Ghaziabad",
  "preference_mismatch_reason": "Location",
  "input_location_had_jobs": "No",
  "nearest_landmark": "Sahibabad station",
  "pin_code": "110098",
  "home_area": "Sahibabad",
  "services_pitched": "Yes",
  "service_interest": "Yes",
  "service_callback_slot": "NA",
  "service_offered": "TRRAIN Trust",
  "service_need_matched": "Placement",
  "jobs_interest": "Yes",
  "jobs_fetched": "Recommended",
  "jobs_offered_count": 2,
  "job_roles_offered": "Data Entry Operator, Computer Operator",
  "job_no_match": "No",
  "asked_job_location": "No",
  "drop_reason": "NA",
  "call_later_request": "NA",
  "final_summary": "Seeker was actively looking for work and engaged in a detailed conversation about three roles. Successfully applied to Electrician and Machine Operator positions but the third application (Solar Energy Consultant) failed due to a profile not found error."
}

Rules:
- Use the exact field names listed above. Do not rename.
- Use "NA" for any string field where the answer is absent.
- Use [] for empty arrays, not "NA".
- Use 0 for empty counts, not "NA".
- For all job arrays (jobs_recommended, jobs_applied, jobs_failed_to_apply), each 
  entry must be a complete object — do not flatten into strings.
- jobs_applied and jobs_failed_to_apply are mutually exclusive at the job level — 
  a single job either succeeded or failed to apply, never both.
- drop_reason captures seeker behavior only, not technical apply failures. If apply 
  failed but the seeker stayed engaged, drop_reason = "NA".
- ready_for_interview is "NA" when the interview-readiness question was never asked 
  or the seeker did not give a clear Yes/No/Conditional answer.
- preferred_location and preference_mismatch_reason describe the caller's STATED
  preference only. Never infer them: if the caller did not say where they want to work,
  preferred_location is "NA" even when the call's input location or their profile carries
  a place. preference_mismatch_reason is "NA" whenever the caller applied to a job or never
  rejected the options. A preferred work location is never written to the caller's profile.
- service_provider_interest is "NA" whenever service_provider_pitched is "No" — a 
  response cannot exist for an offer that was never made. Never infer interest from 
  anything other than the caller's answer to that specific offer.
- Do not hallucinate company names, salaries, or contact details — only extract what 
  is actually present in the transcript or input recommendations.
- For final_summary, always write in English regardless of the conversation language.
}