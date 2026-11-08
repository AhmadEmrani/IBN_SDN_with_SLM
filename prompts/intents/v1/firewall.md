# Firewall create rules v1

Output contract_version 1.0 and capability firewall. Only IPv4 deny is supported.
Preserve host references, explicit IPv4 addresses/CIDRs, and explicit any.
Use authoritative supplied host inventory; unknown host -> unknown_host clarification.
Never convert missing endpoints to any. Missing destination -> missing_destination.
From A to B -> unidirectional. Explicit both directions -> bidirectional.
Bare between A and B -> ambiguous_direction clarification.
Absent protocol and absent ports -> any. Ports with absent protocol ->
ambiguous_protocol clarification (do not infer TCP/UDP from a service port).
Ports: 1..65535, 1..16 unique integers per list, or null for no restriction.
Invalid ports -> invalid_port clarification; never clip or silently discard values.
Ports require TCP/UDP. Bidirectional rules with ports -> unsupported_bidirectional_ports.
Allow -> unsupported_action. IPv6 -> unsupported_ipv6. Time windows/durations ->
unsupported_schedule. Never remove unsupported constraints to make a request pass.
No network ID, DPID, priority, lifecycle ID, cookie or timestamps in the proposal.
Explicit scope/priority/lifecycle requirements outside this proposal contract must
not be dropped: reject as unsupported_action in v1, with an explanatory UI message.
