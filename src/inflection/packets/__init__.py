"""Triage packet pre-assembly (spec 5.3, 6, 9 Mode A, 15 test 12, 17).

For each company in a week's triage shortlist, a frozen, point-in-time packet of the evidence the
triage needs: why it is in the queue now, the trigger passages, earlier comparable disclosures, all
contradicting evidence, a financial snapshot, price and liquidity, and risk flags, inside a token
budget with every cut listed.  ``contents`` builds and renders a packet as pure functions;
``pipeline`` gathers the inputs from the database at the shortlist's cutoff and stores the packet.
"""
