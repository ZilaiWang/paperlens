# Security policy

## Supported versions

Security fixes are provided for the current `main` branch and the latest 1.x
release. Older snapshots may not receive fixes.

## Reporting a vulnerability

Please do not open a public issue, discussion, or pull request containing
exploit details, credentials, private papers, or user data.

Use GitHub's **Report a vulnerability** / private security advisory flow for
this repository when available. If private vulnerability reporting is not
enabled, contact the repository owner through the private contact method listed
on their GitHub profile and include a request for a secure reporting channel.

Include:

- affected version or commit;
- deployment assumptions;
- reproduction steps or a minimal proof of concept;
- impact and data at risk;
- any suggested mitigation;
- whether the issue is already public.

You should receive an acknowledgement within seven days. Please allow time for
triage and a coordinated fix before disclosure.

## Deployment warning

PaperLens 1.0 does not include authentication and uses permissive development
CORS. `X-User-Id` is not trusted identity. Do not expose the API directly to the
public internet. A public deployment needs TLS, authentication, authorization,
origin restrictions, rate limits, upload controls, and protected storage.

Model-backed features can transmit paper excerpts and prompts to the configured
provider. Review provider privacy terms and [Data and privacy](docs/data-and-privacy.md).

## Out of scope

- social engineering without a technical vulnerability;
- denial of service requiring unrealistic local access or unlimited resources;
- vulnerabilities only in unsupported dependencies with no demonstrated impact
  on PaperLens;
- reports that require processing documents the reporter is not authorized to
  share.

This policy does not create a bug-bounty program or promise compensation.
