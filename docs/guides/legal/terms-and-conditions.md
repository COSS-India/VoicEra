## Contents

- [1. Description of VoicEra](#description-of-voicera)
- [2. Definitions](#definitions)
- [3. Open-Source Licence](#open-source-licence)
- [4. Eligibility](#eligibility)
- [5. Accounts and Access](#accounts-and-access)
- [6. Adopter Responsibilities (Shared-Responsibility Model)](#adopter-responsibilities-shared-responsibility-model)
- [7. Acceptable Use](#acceptable-use)
- [8. Hosted Instances](#hosted-instances)
- [9. Intellectual Property and Trademarks](#intellectual-property-and-trademarks)
- [10. Open-Source Standards](#open-source-standards)
- [11. Disclaimer of Warranties](#disclaimer-of-warranties)
- [12. Limitation of Liability](#limitation-of-liability)
- [13. Indemnification](#indemnification)
- [14. Suspension and Termination](#suspension-and-termination)
- [15. Changes to These Terms](#changes-to-these-terms)
- [16. Governing Law and Dispute Resolution](#governing-law-and-dispute-resolution)
- [17. General Provisions](#general-provisions)
- [18. Contact Us](#contact-us)

These Terms and Conditions ("Terms") govern access to and use of VoicEra, an open-source, self-hosted voice AI platform (the "Software"), its documentation, and any VoicEra instance hosted by or for IIIT-Bangalore (a "Hosted Instance"), provided by IIIT-Bangalore (International Institute of Information Technology Bangalore) ("IIIT-Bangalore", "we", "us" or "our"). By deploying, accessing or using VoicEra, you ("Adopter", "User", "you" or "your") agree to these Terms. If you do not agree, do not use VoicEra.

If you use VoicEra on behalf of an organisation, government body or employer, you represent that you have authority to bind that entity, and "you" refers to both you and that entity.

# 1. Description of VoicEra

VoicEra is open-source infrastructure for building real-time voice agents. It connects speech-to-text, large language models, text-to-speech and telephony into one stack that the Adopter installs and runs on infrastructure it controls.

VoicEra is provided as software. For self-hosted deployments, IIIT-Bangalore does not operate the deployment, does not provide telephony or AI inference, and does not receive, store or access any data processed by it. The Adopter brings its own telephony provider, AI providers or self-hosted models, and infrastructure.

# 2. Definitions

- Adopter: the organisation that deploys and operates VoicEra for its own purposes.

- Operator: a person who signs in to an Adopter's VoicEra dashboard or API.

- Caller: a person who speaks with a voice agent built on VoicEra, by phone or browser.

- Hosted Instance: a VoicEra deployment operated by or for IIIT-Bangalore, for example a demonstration or sandbox environment.

- Data Principal and Data Fiduciary: as defined in the Digital Personal Data Protection Act, 2023 ("DPDP Act").

# 3. Open-Source Licence

The VoicEra source code is licensed under the Apache License, Version 2.0, Copyright 2026 IIIT-Bangalore ([<u>https://github.com/COSS-India/VoicEra/blob/main/LICENSE</u>](https://github.com/COSS-India/VoicEra/blob/main/LICENSE)). Nothing in these Terms limits the rights that licence grants. Where these Terms and the licence differ on the use, modification or redistribution of the source code, the licence prevails.

Contributions to the VoicEra repository are accepted under the same licence, as described in CONTRIBUTING.md.

# 4. Eligibility

You must be at least 18 years old to create an Operator account. VoicEra is intended for use by organisations and their authorised personnel.

# 5. Accounts and Access

- You must provide accurate, current information when creating an account.

- You are responsible for keeping your login credentials confidential and for all activity under your account.

- VoicEra provides role-based access control with three roles: member, admin and super_admin ([<u>https://github.com/COSS-India/VoicEra/blob/main/docs/developer/reference/multi-tenancy.md</u>](https://github.com/COSS-India/VoicEra/blob/main/docs/developer/reference/multi-tenancy.md)).

- The Adopter decides which Operators hold which role and sets its own access policies, including periodic review and timely removal of access.

- Report any unauthorized usage of accounts. For self-hosted deployments, report it to the Adopter that operates the deployment.

# 6. Adopter Responsibilities (Shared-Responsibility Model)

VoicEra is business-to-business infrastructure. IIIT-Bangalore builds and maintains the Software; the Adopter decides how it is used and is responsible for the data it processes. In particular, the Adopter:

- is the Data Fiduciary under the DPDP Act for all personal data processed in its deployment, including Callers' phone numbers, call recordings, transcripts, contact lists and uploaded documents;

- must give Callers notice and obtain consent where required, in a language they understand, including disclosing that the call is recorded and that they are speaking with an automated agent. VoicEra records every call; its optional recording-disclosure prompt template asks the agent to read a disclosure but does not guarantee it, so the Adopter must provide its own notice and consent mechanism;

- must configure role-based access control, assign roles, and define and enforce its own access, retention and deletion policies;

- must secure its deployment, following the VoicEra security hardening guide ([<u>https://voicera.mintlify.app/docs/guides/deployment/security-hardening</u>](https://voicera.mintlify.app/docs/guides/deployment/security-hardening)), including changing default credentials, enabling TLS, encrypting storage and setting a retention policy;

- must handle requests from Data Principals (access, correction, erasure, grievance) and keep its own audit records;

- selects, contracts with and is bound by the terms of any third-party telephony, speech or language-model provider it configures;

- must comply with telecom rules for any calling it performs, including the TRAI Telecom Commercial Communications Customer Preference Regulations, 2018, do-not-disturb preferences and permitted calling hours; and

- must obtain verifiable parental consent where it processes the personal data of children, as required by Section 9 of the DPDP Act.

# 7. Acceptable Use

You agree not to use VoicEra to:

- make unlawful, fraudulent, deceptive or unsolicited calls, or calls that breach telecom regulations;

- impersonate any person or organisation, or clone or imitate a real person's voice without their consent;

- harass, threaten, abuse or discriminate against any person;

- create, store or transmit child sexual abuse material or any other illegal content;

- collect personal data without a lawful basis, or process it beyond the purpose notified to the Data Principal;

- attempt unauthorised access to any account, deployment or underlying infrastructure; or

- upload malware or disrupt the security or integrity of any deployment.

IIIT-Bangalore may suspend access to any Hosted Instance for violations of this section.

# 8. Hosted Instances

Where IIIT-Bangalore provides a Hosted Instance for evaluation, training or demonstration:

- it is a non-production environment and may be reset, wiped or reconfigured at any time without notice;

- data in it is not guaranteed to be backed up or preserved;

- you should not enter real personal data, confidential information or payment details unless IIIT-Bangalore has agreed otherwise in writing; and

- features may change, be added or be removed at any time.

Where IIIT-Bangalore hosts an instance on behalf of an Adopter under a separate written agreement, that agreement governs and prevails over this section.

# 9. Intellectual Property and Trademarks

The source code is available under the Apache License 2.0 (Section 3). Documentation is licensed under Apache License 2.0, the same licence as the source code. The VoicEra name and logo are not licensed for use except as needed to describe the origin of the Software, as provided in Section 6 of the Apache License 2.0.

You retain ownership of the content you create or upload in your deployment, including agent prompts, documents and call data.

# 10. Open-Source Standards

IIIT-Bangalore maintains VoicEra as an open-source project following open-source best practices: public source code, a documented contribution process (CONTRIBUTING.md), a Code of Conduct (CODE_OF_CONDUCT.md), and private vulnerability disclosure (SECURITY.md).

# 11. Disclaimer of Warranties

VOICERA IS PROVIDED "AS IS" AND "AS AVAILABLE", WITHOUT WARRANTIES OF ANY KIND, WHETHER EXPRESS, IMPLIED OR STATUTORY, INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, OR THAT IT WILL BE UNINTERRUPTED, SECURE OR ERROR-FREE. AI-GENERATED RESPONSES MAY BE INACCURATE, AND THE ADOPTER IS RESPONSIBLE FOR REVIEWING HOW ITS AGENTS BEHAVE.

# 12. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, IIIT-BANGALORE AND ITS OFFICERS, EMPLOYEES, CONTRIBUTORS AND AFFILIATES SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL OR PUNITIVE DAMAGES, OR ANY LOSS OF DATA, PROFITS OR GOODWILL, ARISING FROM THE USE OF OR INABILITY TO USE VOICERA, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. Some jurisdictions do not allow certain limitations of liability, so some of these limitations may not apply to you.

# 13. Indemnification

The Adopter agrees to indemnify and hold harmless IIIT-Bangalore from any claims, damages, liabilities and expenses (including reasonable legal fees) arising from its deployment or use of VoicEra, its processing of personal data, or its breach of these Terms or applicable law.

# 14. Suspension and Termination

You may stop using a Hosted Instance and request deletion of your account at any time by emailing the authorized support team of the provider who has created your account on the infrastructure. Termination does not affect rights granted under the Apache License 2.0.

# 15. Changes to These Terms

IIIT-Bangalore may update these Terms from time to time. The updated version will be published in the VoicEra documentation with a new "Last Updated" date. Continued use after an update means you accept the revised Terms.

# 16. Governing Law and Dispute Resolution

These Terms are governed by the laws of India, without regard to conflict-of-law principles. Any dispute arising from these Terms or VoicEra shall be resolved in the courts of Bengaluru, Karnataka.

# 17. General Provisions

- Entire agreement: these Terms, together with the Privacy Policy and the Apache License 2.0, form the entire agreement between you and IIIT-Bangalore regarding VoicEra.

- Severability: if any provision is found unenforceable, the remaining provisions remain in effect.

- No waiver: failure to enforce a provision is not a waiver of the right to enforce it later.

- Assignment: you may not assign these Terms without IIIT-Bangalore's consent; IIIT-Bangalore may assign them.

# 18. Contact Us

IIIT-Bangalore, 26/C, Opposite of Infosys Gate 10, Electronics City Phase 1, Hosur Road, Bengaluru, Karnataka 560100, India

Email: support@ai4inclusion.org
