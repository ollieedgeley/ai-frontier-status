# README header research

Reviewed the first-party README sources on 15 September 2026. These observations concern the source layout; they do not establish that a particular layout caused a project's popularity.

## Examples

| Project | Header and links | Images | Useful pattern |
| --- | --- | --- | --- |
| [Starship](https://github.com/starship/starship/blob/main/README.md) | The logo, badges and short navigation row each use a centered paragraph. Status badges and community badges occupy separate lines. Sponsorship has its own section further down. | The centered logo has an explicit width. A demonstration image sits beside the introduction further down. | Separate navigation from badges and align each row consistently. |
| [Immich](https://github.com/immich-app/immich/blob/main/README.md) | Badges, the logo and the short product description are centered. Documentation and contribution links appear in a later section. | A large product screenshot follows the centered identity. | Give the project name and description a clear position above its screenshot. |
| [LocalSend](https://github.com/localsend/localsend/blob/main/README.md) | A standard Markdown title precedes badges and a compact text-link row with dot separators. The header has no explicit centering. Sponsors have a separate section. | Desktop and phone screenshots share a row at a common height in the screenshots section. | Keep navigation compact and retain detailed screenshots as documentation. |
| [Syncthing](https://github.com/syncthing/syncthing/blob/main/README.md) | A linked project logo precedes a divider and three badges. The header has no explicit centering. Contact and documentation links have later sections. | The header uses the project logo without a product screenshot. | Keep the opening brief and make the project identity immediately recognisable. |

The sources inspected were the raw READMEs for [Starship](https://raw.githubusercontent.com/starship/starship/main/README.md), [Immich](https://raw.githubusercontent.com/immich-app/immich/main/README.md), [LocalSend](https://raw.githubusercontent.com/localsend/localsend/main/README.md), and [Syncthing](https://raw.githubusercontent.com/syncthing/syncthing/main/README.md).

## Recommendation for AI Frontier Status

Center the project title and existing description, then use one compact navigation row and one row for Ollie's X, Buy Me a Coffee and PayPal badges. Restore the badge colours that preceded the charcoal revision, including the requested purple coffee badge. Keep the original project image beneath the header and preserve both panel screenshots in their existing section.

This combines Starship's distinct link rows with Immich's centered identity and prominent product image. The existing AI Frontier Status image and Ollie's selected colours give it its own appearance. Keep the rest of the README left-aligned so commands, configuration and the company list remain easy to read.

Use the existing README section names for navigation labels and targets. Review the rendered header at desktop and narrow widths, check that the three account URLs remain exact, and confirm that all three existing image references survive the edit.
