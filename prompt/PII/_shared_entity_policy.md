# Entity taxonomy and policy

**Prompt version:** `pii-v7-entity-policy-1`

This taxonomy is shared by PII discovery, plan generation, rewriting and
verification. One definition, used identically by all four.

## The question that decides everything

> Could this value, on its own or combined with the rest of the conversation,
> identify a **real person**, a **private project**, a **private organization**,
> an **account**, a **private communication endpoint**, or a **private technical
> resource**?

If yes, it is privacy-sensitive. If it is merely the *name of a public product
or company*, it is not.

## Entity types

**Directly identifying a person**

| Type | Meaning |
|---|---|
| `PERSON` | A real person's name, or any part of one used as a name |
| `EMAIL` | An email address |
| `PHONE` | A telephone number |
| `PERSONAL_USERNAME` | A login or handle belonging to a person |
| `SOCIAL_ACCOUNT` | A social-media account or `@handle` |

**Identifying a private project or organization**

| Type | Meaning |
|---|---|
| `PROJECT_NAME` | A private project, product or brand name, e.g. an invented product alias |
| `PRIVATE_ORGANIZATION` | A company or team that is not a public, widely known entity |
| `PRIVATE_DOMAIN` | A domain owned by the project or a participant |
| `PRIVATE_REPOSITORY` | A repository name or path specific to this project |
| `PRIVATE_URL` | A link to a private resource, dashboard, file or environment |
| `MEETING_URL` | A call or meeting link |

**Place and personal circumstance**

| Type | Meaning |
|---|---|
| `LOCATION` | A specific place tied to a participant |
| `ADDRESS` | A postal address |
| `PERSONAL_CONTEXT` | A personal circumstance that narrows identity (an employer, a school, a named family member) |
| `UNIQUE_BIOGRAPHICAL_DETAIL` | A detail rare enough to identify someone on its own |

**Accounts and chain identifiers**

| Type | Meaning |
|---|---|
| `ACCOUNT_IDENTIFIER` | An account number, customer id, tenant id or similar |
| `WALLET_ADDRESS` | A blockchain address |

**Credentials**

| Type | Meaning |
|---|---|
| `SECRET` | A credential visible in the text |
| `SECRET_CANDIDATE` | A `<SECRET_CANDIDATE:...>` protected token — a credential already removed before you saw it |

**Not privacy-sensitive**

| Type | Meaning |
|---|---|
| `PUBLIC_THIRD_PARTY` | A public company or service: GitHub, Stripe, AWS, Brevo, Google, Zoom, Figma, JLCPCB, Upwork, … |
| `PUBLIC_TECHNOLOGY` | A public technology, protocol, standard or domain concept: OAuth, USDC, ERC-721, AES-256, PostgreSQL, React Native, KYC, … |
| `NON_PII` | Anything else you were asked about that turns out not to be sensitive |

## Policy is fixed by type

You do not choose the policy. It follows from the type, and a mismatch is
rejected.

| Policy | Types | Meaning |
|---|---|---|
| `SYNTHESIZE` | every person, project, place, account and chain type above | Replaced by a realistic fictional value |
| `PRESERVE` | `PUBLIC_THIRD_PARTY`, `PUBLIC_TECHNOLOGY`, `NON_PII` | Kept exactly as written |
| `PROTECTED` | `SECRET`, `SECRET_CANDIDATE` | Handled outside the model entirely |

## Public names are kept

A public company, service or technology is **not** sensitive merely because it
is named. "We deploy on AWS and take payments through Stripe" names two real
companies and identifies nobody — and both names are part of the project's
requirements, so removing them would destroy information the dataset exists to
preserve.

Keep them. Classify them `PUBLIC_THIRD_PARTY` or `PUBLIC_TECHNOLOGY`.

The distinction is **public versus private**, not "company versus not":

- `Stripe`, `GitHub`, `Brevo`, `Transak`, `Uniswap` → `PUBLIC_THIRD_PARTY`, preserved.
- `BooksOnChain`, `Project Rebuild`, `northstar.io` → private, synthesized.

A public *company* name and a *private* resource hosted with that company are
different things: `github.com` is public, but `github.com/acme-private/ledger`
is a `PRIVATE_REPOSITORY`.

## Requirement-bearing terms are kept

Tool names, frameworks, protocols, standards, feature mechanics and other
requirement vocabulary are never treated as private names, even when they look
like invented words. `OAuth`, `USDC`, `ETH`, `KYC`, `ERC-721`, `AES-256`,
`gamification mechanics` all stay.

Changing a technical identifier changes the requirement. `ERC-721` is not
`ERC-742`.
