# goAML schema

`goaml-5.0.1.xsd` is the goAML XML schema (`goaml:schemaVersion="5.0.1"`, application version 5.0),
downloaded unchanged on 2026-10-20 from the Cellule de Renseignement Financier (CRF), Luxembourg:

- Page: https://crf.public.lu/en/comment/faq/tech/sujets-it.html ("goAMLSchema 5_0 final")
- File: https://crf.public.lu/dam-assets/faq/goamlschema-5-0-final.txt (published as `.txt`)
- SHA-256: `73a220e801731ef1346dcb916f5223c29a306ce1d67adb12c680bb33d03ed9fd`

goAML is UNODC's reporting platform; each FIU distributes the schema with its own adaptations.
This copy carries Luxembourg's: the local currency is fixed to EUR, some optional elements are
removed (`maxOccurs="0"`), and XSD 1.1 assertions encode the CRF's rejection rules (`REJ-…`).
Validation therefore needs an XSD 1.1 processor (`xmlschema.XMLSchema11`). No licence is stated
on the source page.
