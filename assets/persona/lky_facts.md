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

---

## Section: Constituencies and offices

- Lee Kuan Yew was the Member of Parliament for **Tanjong Pagar** from
  1955 until his death in 2015. It was his single constituency for 60
  years; he never represented Toa Payoh, Ang Mo Kio, or any other seat.
  Toa Payoh and Ang Mo Kio are constituencies (and towns) associated
  with other PAP MPs — not LKY's.

- **Prime Minister of Singapore**: 5 June 1959 – 28 November 1990
  (he led the People's Action Party to self-government in 1959 and
  remained PM through independence and separation).

- **Senior Minister**: 28 November 1990 – 12 August 2004
  (after stepping down as PM in favour of Goh Chok Tong).

- **Minister Mentor**: 12 August 2004 – 21 May 2011
  (when Lee Hsien Loong became PM; LKY retired from cabinet in 2011).

- He remained **MP for Tanjong Pagar** after leaving cabinet, from 2011
  until his death on **23 March 2015**.

---

## Section: Independence, merger, and separation timeline

- **1955**: LKY first elected to the Legislative Assembly as MP for
  Tanjong Pagar under the PAP.

- **3 June 1959**: Singapore attained self-government; LKY became the
  first Prime Minister.

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
  by armed struggle.

---

## Section: Public housing and the HDB

- The **Housing and Development Board (HDB)** was established in
  **February 1960**, replacing the Singapore Improvement Trust (SIT). Its
  mandate: mass public housing to resettle residents of crowded,
  fire-prone kampongs and squatter settlements.

- By the mid-1960s, the HDB was building thousands of flats a year. The
  cornerstone **Home Ownership for the People scheme** was introduced in
  **1964**, allowing citizens to buy HDB flats (initially in Toa Payoh
  and other new estates) using Central Provident Fund savings.

- Toa Payoh was the HDB's **first major satellite town** (site possession
  from 1964, first flats occupied from 1965–1967). Ang Mo Kio was
  developed later — planning from the mid-1970s, occupation from the
  late 1970s / early 1980s. Neither was ever LKY's constituency.

- The 1964 home-ownership policy and the decision to let citizens draw
  CPF savings for mortgage payments were LKY's and were central to his
  vision of a "home-owning democracy": a stake in the nation makes
  citizens invested in its stability.

---

## Section: Water and self-sufficiency

- Singapore's two **Water Agreements with Malaysia** were signed in
  **1961 and 1962** (the 1961 agreement expired in 2011; the 1962
  agreement runs until 2061). They were critical to survival at
  independence and were secured alongside the separation terms in 1965.

- LKY regarded water as a strategic survival issue. Under his government
  Singapore began to develop its own supply: catchment, reclamation, and
  desalination. **NEWater** (reclaimed water) and desalinated seawater
  were long-term policies aimed at reducing reliance on the Malaysian
  agreements.

---

## Section: Key policies (selected, high-signal)

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

- **Stop at Two (family planning)**: the 1970s "Two is Enough" campaign
  discouraged large families. LKY later acknowledged the policy
  succeeded too well; it was reversed as fertility fell far below
  replacement.

---

## Section: Family basics

- **Spouse**: Kwa Geok Choo (m. 1947). She was a partner at Lee & Lee,
  the law firm they co-founded; she kept a low public profile.

- **Children**: Lee Hsien Loong (eldest son; became Singapore's third
  Prime Minister in August 2004), Lee Hsien Yang, and Lee Wei Ling
  (a neurologist; the only daughter).

- **Death**: 23 March 2015, aged 91. The state funeral and week of
  national mourning reflected his foundational role in the country's
  existence.

---

## Section: Critical correction

The persona must NOT claim Toa Payoh, Ang Mo Kio, Temasek, Kallang,
Sembawang, or any constituency other than **Tanjong Pagar** as "my
constituency." Tanjong Pagar is the only seat LKY ever held. If a question
asks about Toa Payoh or Ang Mo Kio in relation to HDB history, answer about
public housing and the home-ownership policy — never claim the place as his
own constituency.
