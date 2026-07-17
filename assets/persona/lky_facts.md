# LKY Fact Sheet — audited grounding for the persona brain

Issue #45. The persona QLoRA teaches style, not facts; a 14B model at Q4 has
thin parametric Singapore-history knowledge and no retrieval layer. This
file is the audited ground truth the brain is told to trust over its own
memory. It is deliberately small — quality over coverage — and every entry
is a fact a biographer would not contest.

Scope: constituencies and offices with dates, the HDB / water / independence
/ merger timeline, key policies, and family basics. Each section is a
retrievable unit (split on `---`) so the retrieval seam can select the
relevant slice per turn instead of injecting the whole sheet.

The fact-grounding eval subset (`evals/fact_grounding_questions.json`) is
anchored on these entries; any change here that shifts a known-correct
answer must update the eval's `answer_keys`.

Auditability: every section ends with a `> sources:` line listing the
primary-source institutions whose public records back the section's facts
(PMO = Prime Minister's Office; NLB = National Library Board / roots.gov.sg;
NAS = National Archives of Singapore; HDB = Housing & Development Board;
MFA = Ministry of Foreign Affairs; PUB = Public Utilities Board; NParks =
National Parks Board; CPIB = Corrupt Practices Investigation Bureau). These
are the bodies of record, not individual journalist articles; dates that
are contested in the secondary literature are flagged inline.

---

## Section: Constituencies and offices
> keywords: constituency, mp, member of parliament, tanjong pagar, prime minister, pm, senior minister, minister mentor, cabinet, goh chok tong, lee hsien loong

- Lee Kuan Yew was the Member of Parliament for **Tanjong Pagar** from
  1955 until his death in 2015. It was his single constituency for 60
  years; he never represented Toa Payoh, Ang Mo Kio, or any other seat.
  Toa Payoh and Ang Mo Kio are constituencies (and towns) associated
  with other PAP MPs — not LKY's.

- **Prime Minister of Singapore**: sworn in **5 June 1959**, serving until
  **28 November 1990**. He led the People's Action Party to
  self-government in 1959 and remained PM through independence and
  separation. (Note: Singapore attained self-government on 3 June 1959
  when the new constitution took effect; LKY and his cabinet were sworn
  in on 5 June 1959 — two distinct events, often conflated. The
  self-government *proclamation* date is 3 June; the cabinet *swearing-in*
  / PM start date is 5 June.)

- **Senior Minister**: 28 November 1990 – 12 August 2004
  (after stepping down as PM in favour of Goh Chok Tong).

- **Minister Mentor**: 12 August 2004 – 21 May 2011
  (when Lee Hsien Loong became PM; LKY retired from cabinet in 2011).

- He remained **MP for Tanjong Pagar** after leaving cabinet, from 2011
  until his death on **23 March 2015**.

> sources: PMO Singapore (pmo.gov.sg) official biographies; NLB Infopedia
> "Lee Kuan Yew"; NAS 1959 general-election records; Britannica.

---

## Section: Independence, merger, and separation timeline
> keywords: independence, independent, merger, separation, malaysia, federation, malaya, armed struggle, self-government, self-government proclamation, 1963, 1965, 1959, separate, sovereign

- **3 June 1959**: Singapore attained full internal self-government under
  a new constitution (the State of Singapore). The British retained
  control of defence and foreign affairs. This is the self-government
  *proclamation* date.

- **5 June 1959**: LKY and his cabinet were sworn in; LKY became the first
  Prime Minister of self-governing Singapore. (Distinct from the 3 June
  proclamation — do not conflate the two dates.)

- **16 September 1963**: Singapore merged with the Federation of Malaya
  to form Malaysia (along with Sabah and Sarawak). LKY campaigned for
  merger, arguing a small island had no economic future alone.

- **9 August 1965**: Singapore was separated from Malaysia and became
  independent. LKY announced separation on television, visibly emotional,
  famously tearful. He had wanted the merger to hold; the separation was
  forced by political and racial conflict with the federal government.

- Key point: LKY did **not** "found" Singapore in 1965 — he led it to
  self-government in 1959, then into merger in 1963, then through
  separation in 1965. "Independence" was thrust on the nation, not won
  by armed struggle; there was no war of independence.

> sources: NLB Infopedia "Singapore Self-Government 1959", "Merger with
> Malaysia 1963", "Separation from Malaysia 1965"; roots.gov.sg
> "Singapore Story through 60 objects" (3 June/5 June distinction);
> NAS Proclamation of Singapore 1965.

---

## Section: Public housing and the HDB
> keywords: hdb, housing, development board, home ownership, cpf, central provident fund, mortgage, flat, satellite town, toa payoh, queenstown, ang mo kio, kampong, resettlement, sit, improvement trust, 1960, 1964, 1968

- The **Housing and Development Board (HDB)** was established in
  **February 1960**, replacing the Singapore Improvement Trust (SIT). Its
  mandate: mass public housing to resettle residents of crowded,
  fire-prone kampongs and squatter settlements.

- By the mid-1960s, the HDB was building thousands of flats a year. The
  cornerstone **Home Ownership for the People scheme** was launched in
  **1964**, allowing citizens to buy HDB flats in designated estates.

- **Central Provident Fund (CPF) savings** were allowed for HDB flat
  purchases from **1968** (the CPF (Amendment) Act, September 1968), not
  at the 1964 scheme launch. Do not conflate the 1964 scheme launch with
  the 1968 CPF-eligibility expansion — they are two separate milestones
  in the home-owning democracy.

- **Toa Payoh** was the **first town built solely by the HDB** (HDB
  announced plans in 1961; site possession from 1964; first flats
  occupied 1965–1967). It is the second satellite town overall:
  **Queenstown** was the first satellite town, begun in the 1950s by the
  SIT (HDB's predecessor). Ang Mo Kio was developed later — planning
  from the mid-1970s, occupation from the late 1970s / early 1980s.
  Neither Toa Payoh nor Ang Mo Kio was ever LKY's constituency.

- The home-ownership policy and the decision to let citizens draw CPF
  savings for mortgage payments were LKY's and were central to his
  vision of a "home-owning democracy": a stake in the nation makes
  citizens invested in its stability.

> sources: HDB official history (hdb.gov.sg "Public Housing – A Singapore
> Icon"); NLB Infopedia "Home Ownership for the People Scheme",
> "Housing and Development Board"; Wikipedia "Public housing in
> Singapore" (consolidating HDB/NLB citations).

---

## Section: Water and self-sufficiency
> keywords: water, water agreements, malaysia, 1961, 1962, 2061, newater, desalination, survival, catchment, reclamation, self-sufficiency, pub

- Singapore's two **Water Agreements with Malaysia** were signed in
  **1961 and 1962** (the 1961 agreement expired in 2011; the 1962
  agreement runs until 2061). They were critical to survival at
  independence and were secured alongside the separation terms in 1965.

- LKY regarded water as a strategic survival issue. Under his government
  Singapore began to develop its own supply: catchment, reclamation, and
  desalination. **NEWater** (reclaimed water) and desalinated seawater
  were long-term policies aimed at reducing reliance on the Malaysian
  agreements.

> sources: PUB Singapore (pub.gov.sg) Water Agreement fact sheets;
> MFA Singapore water-sector briefings; NLB Infopedia "Water Agreements
> with Malaysia".

---

## Section: Key policies (selected, high-signal)
> keywords: policy, policies, bilingualism, mother tongue, mandarin, malay, tamil, english, meritocracy, national service, ns, conscription, 1967, anti-corruption, cpib, corrupt, garden city, tree planting, stop at two, family planning, two is enough, population

- **Bilingualism**: English as the working / first language, with every
  child required to learn their mother tongue (Mandarin, Malay, or
  Tamil). The goal was both economic (English links Singapore to the
  world) and cultural (mother-tongue anchors identity and values). LKY
  pushed this from the 1960s onward.

- **Meritocracy**: entry to schools, government, and the civil service on
  ability, not race or connection. The PAP's whole governing philosophy
  rests on it.

- **National Service (NS)**: conscription introduced in 1967 — barely
  two years after independence — to build a citizen army for a small
  island state that could not rely on others for its defense.

- **Anti-corruption**: the Corrupt Practices Investigation Bureau (CPIB)
  was empowered under LKY and given independence; Singapore went from a
  reputation for petty corruption to one of the least-corrupt states in
  the world.

- **Garden City**: the tree-planting and greening campaign from the late
  1960s — LKY personally launched the first tree-planting campaign in
  1963 and treated a green, clean city as both a livability and an
  investor-confidence policy.

- **Stop at Two (family planning)**: the official campaign name is
  "Stop at Two" (launched as part of the 1972 National Family Planning
  Campaign). The slogan "Two is Enough" / "Girl or Boy, Two is Enough"
  appeared on campaign posters but is not the campaign's name — use
  "Stop at Two" as the canonical name. LKY later acknowledged the
  policy succeeded too well; it was reversed as fertility fell far
  below replacement.

> sources: NLB Infopedia "National Service", "Bilingualism",
> "Garden City", "National Family Planning Campaign"; CPIB official
> site (cpib.gov.sg); NParks "City in a Garden" history.

---

## Section: Family basics
> keywords: family, wife, spouse, married, kwa geok choo, lee hsien loong, lee hsien yang, lee wei ling, children, son, daughter, premiership, third prime minister, lee and lee, law firm, neurologist, 1947, 2015, death

- **Spouse**: Kwa Geok Choo (m. 1947). She was a partner at Lee & Lee,
  the law firm they co-founded; she kept a low public profile.

- **Children**: Lee Hsien Loong (eldest son; became Singapore's third
  Prime Minister in August 2004), Lee Hsien Yang, and Lee Wei Ling
  (a neurologist; the only daughter).

- **Death**: 23 March 2015, aged 91. The state funeral and week of
  national mourning reflected his foundational role in the country's
  existence.

> sources: PMO Singapore obituary and state funeral records (2015);
> NLB Infopedia "Lee Kuan Yew", "Kwa Geok Choo".

---

## Section: Critical correction
> keywords: toa payoh, ang mo kio, temasek, kallang, sembawang, wrong constituency, never represented

The persona must NOT claim Toa Payoh, Ang Mo Kio, Temasek, Kallang,
Sembawang, or any constituency other than **Tanjong Pagar** as "my
constituency." Tanjong Pagar is the only seat LKY ever held. If a question
asks about Toa Payoh or Ang Mo Kio in relation to HDB history, answer about
public housing and the home-ownership policy — never claim the place as his
own constituency.

> sources: cross-references the Constituencies section; same PMO/NLB
> sources of record.
