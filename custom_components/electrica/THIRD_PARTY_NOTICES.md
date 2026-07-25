# Third-party notices

## cnecrea/myelectrica

While mapping the Electrica România API, the public repository
<https://github.com/cnecrea/myelectrica> (MIT licensed) was consulted as a
reference for **which API endpoints exist and what shape their requests take**.

No source code was copied. Every module in this integration — the HTTP client,
the parser and typed models, the coordinator, the entities, encryption,
statistics, diagnostics and tests — was written independently, and the endpoint
behaviour was verified against the live API.

The overlap is limited to facts about Electrica's interface, which cannot be
implemented differently without breaking interoperability:

- the API base URL and endpoint paths (including Electrica's own misspelling of
  `consumtion-convention`);
- the Romanian request field names (`parola`, `versiune`);
- bearer-token authentication and the `app_token` response field;
- the SAP-derived response field names (`IdLocConsum`, `to_ContContract`,
  `to_LocConsum`, `SerieContor`, `PACIndicator`, …);
- the nested payload required by `set-index`;
- the path-parameter ordering used by the invoice and payment endpoints.

Two conventions were, however, adopted from that project rather than being
required by the API — the two-year (730-day) look-back used when requesting
invoice and payment history, and lower-casing the boolean `unpaid` path segment.

Its licence is reproduced below in full, as its terms require for any copy or
substantial portion. This notice is included because that repository was
genuinely used as a reference; it is not an admission that any protected
expression was reproduced.

Nothing here relates to that project's licensing/activation system, which was
not examined, used, adapted, or circumvented in any way.

---

```
Licență MIT

Copyright (c) 2024 [cnecrea]

Prin prezenta se acordă permisiunea, gratuit, oricărei persoane care intră în posesia
unei copii a acestui software și a fișierelor de documentație asociate (denumite în
continuare „Software”), să utilizeze Software-ul fără restricții, inclusiv, dar fără a
se limita la drepturile de a folosi, copia, modifica, fuziona, publica, distribui,
sublicenția și/sau vinde copii ale Software-ului, și de a permite persoanelor cărora le
este furnizat Software-ul să facă acest lucru, sub rezerva următoarelor condiții:

Notificarea de copyright de mai sus și această notificare de permisiune vor fi incluse
în toate copiile sau porțiunile substanțiale ale Software-ului.

SOFTWARE-UL ESTE FURNIZAT „CA ATARE”, FĂRĂ NICIUN FEL DE GARANȚIE, EXPRESĂ SAU
IMPLICITĂ, INCLUSIV, DAR FĂRĂ A SE LIMITA LA GARANȚIILE DE COMERCIALIZARE,
POTRIVIRE PENTRU UN ANUMIT SCOP ȘI NEÎNCĂLCARE. ÎN NICIUN CAZ AUTORII SAU
DEȚINĂTORII DREPTURILOR DE AUTOR NU VOR FI RĂSPUNZĂTORI PENTRU NICIUN FEL DE
PRETENȚII, DAUNE SAU ALTE RĂSPUNDERI, FIE ÎNTR-O ACȚIUNE CONTRACTUALĂ, DELICTUALĂ
SAU ÎN ALTE CAZURI, CARE DECURG DIN, DIN SAU ÎN LEGĂTURĂ CU SOFTWARE-UL SAU
UTILIZAREA SAU ALTE INTERACȚIUNI CU SOFTWARE-UL.
```

---

## Electrica România

"Electrica" and "Electrica Furnizare" are trademarks of their respective owners.
This is an unofficial, community-built integration and is not affiliated with,
endorsed by, or supported by Electrica România.

## Home Assistant

"Home Assistant" and its logo are trademarks of the Open Home Foundation. This
integration is a third-party component and is not an official Home Assistant
product.
