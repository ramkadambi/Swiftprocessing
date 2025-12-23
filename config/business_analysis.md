Fields needed for routing from MT/MX
| Purpose           | MT103 Field | MX pacs.008 Field    |
| ----------------- | ----------- | -------------------- |
| Sender bank       | :52A        | InstgAgt             |
| Intermediary bank | :56A        | IntrmyAgt1           |
| Creditor bank     | :57A        | CdtrAgt              |
| Beneficiary       | :59         | Cdtr                 |
| Amount            | :32A        | IntrBkSttlmAmt       |
| Currency          | :32A        | IntrBkSttlmAmt Ccy   |
| Urgency           | :23B / :71A | PmtTpInf / InstrPrty |
| Country inference | BIC         | BIC                  |
| End-to-end ID     | :20         | EndToEndId           |

Canonical Routing structure
{
  "payment_id": "E2E-IND-0001",

  "amount": {
    "currency": "USD",
    "value": 1500000
  },

  "participants": {
    "sender_bank": {
      "bic": "SBININBBXXX",
      "country": "IN"
    },
    "intermediary_bank": {
      "bic": "WFBIUS6SXXX",
      "country": "US"
    },
    "creditor_bank": {
      "bic": "BOFAUS3NXXX",
      "country": "US"
    }
  },

  "beneficiary": {
    "name": "ACME CORP",
    "account": "021000021",
    "country": "US",
    "type": "BANK | INDIVIDUAL"
  },

  "routing_context": {
    "urgency": "NORMAL | HIGH",
    "customer_preference": "FED | CHIPS | NONE"
  },

  "enrichment": {
    "bic_lookup": {},
    "account_validation": {},
    "routing_decision": {}
  }
}

Key rule - Canonical object never stores MT- or MX-specific syntax.

Scenario 1 — India → Wells Customer (IBT)
MT103 (Inbound)
:20:IN0001
:23B:CRED
:32A:250918USD50000,
:52A:SBININBBXXX
:57A:WFBIUS6SXXX
:59:/123456789
JOHN DOE
NEW YORK US

Scenario 2 — India → Wells → Bank of America (CHIPS)
MT103 (Inbound)
:20:IN0002
:32A:250918USD5000000,
:52A:SBININBBXXX
:56A:WFBIUS6SXXX
:57A:BOFAUS3NXXX
:59:/987654321
ACME CORP
NEW YORK US

Scenario 2 — India → Wells → Bank of America (CHIPS)
MT103 (Inbound)
<CdtTrfTxInf>
  <PmtId>
    <EndToEndId>E2E-003</EndToEndId>
  </PmtId>
  <IntrBkSttlmAmt Ccy="USD">200000</IntrBkSttlmAmt>
  <PmtTpInf>
    <InstrPrty>HIGH</InstrPrty>
  </PmtTpInf>
  <InstgAgt>
    <FinInstnId><BICFI>SBININBBXXX</BICFI></FinInstnId>
  </InstgAgt>
  <IntrmyAgt1>
    <FinInstnId><BICFI>WFBIUS6SXXX</BICFI></FinInstnId>
  </IntrmyAgt1>
  <CdtrAgt>
    <FinInstnId><BICFI>BOFAUS3NXXX</BICFI></FinInstnId>
  </CdtrAgt>
</CdtTrfTxInf>

Scenario 4 — India → Wells → Mexico Bank (SWIFT Out)
MT103 (Inbound)
:52A:SBININBBXXX
:56A:WFBIUS6SXXX
:57A:BAMXMXMMXXX
:59:/4455667788
GLOBAL IMPORTS
MEXICO CITY MX

