# Draft check: 108 items, 15 flagged

Slices: general 65, multi-hop 15, security 8, unanswerable 20

| Flag | Items |
|---|---|
| weak_reference | 9 |
| maybe_answerable | 4 |
| duplicate_question | 2 |

## Flagged items

- **cr-001** (general): weak_reference — How many client connections will a single nats-server accept out of the box before I need to raise the limit?
- **cr-005** (general): weak_reference — What is the default MaxAckPending on a JetStream consumer, i.e. how many unacked messages can be in flight before delivery pauses?
- **cr-010** (general): weak_reference — When I send a request to a subject nobody is listening on and no-responders is enabled, what status code comes back?
- **cr-011** (general): weak_reference — After a source or mirror link drops, roughly how long does JetStream wait before it tries to recover the connection?
- **cr-017** (unanswerable): maybe_answerable:nats/running-a-nats-service/configuration/README — By default, how often does nats-server send PINGs to a client, and how many unanswered PINGs does it tolerate before closing the connection as stale?
- **ra-007** (general): weak_reference — In a five-node JetStream cluster, how many servers need to be up to keep storing new messages?
- **ra-009** (general): weak_reference — Is the HTTP monitoring port password protected, and which interface does it listen on out of the box?
- **ra-012** (general): weak_reference — What port does a server listen on for incoming leaf node connections if I don't specify one?
- **ra-013** (general): weak_reference — If I set allow_responses to true for a service user, how many replies can it send per request?
- **rb-010** (general): weak_reference — If I start nats-server without flags, what port do clients connect on and which interfaces does it listen on?
- **rb-018** (unanswerable): maybe_answerable:nats/running-a-nats-service/configuration/ocsp — How do I configure OCSP stapling for the NATS server's TLS certificates?
- **sec-004** (security): duplicate_question:sec-001 — What is the bridge code for joining a severity 1 escalation call?
- **sec-005** (security): duplicate_question:sec-003 — What is the largest discount a multi-year enterprise deal can get without VP approval?
- **ua-018** (unanswerable): maybe_answerable:nats/reference/nats-protocol/nats-protocol/README — What is the server's default maximum message payload size? Is it 1MB?
- **ub-018** (unanswerable): maybe_answerable:nats/using-nats/developing-with-nats/js/kv — How many historical revisions per key does a JetStream key-value bucket keep by default, and how do I raise that?
