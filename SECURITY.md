# Security and responsible reporting

Do not publish production configuration files, private IPs, authentication
tokens, inverter serial numbers, EVCC API credentials, or raw system logs.

For a potential vulnerability, contact the repository maintainer privately
rather than posting secrets in a public GitHub issue. The repository owner
should configure GitHub's private vulnerability reporting before publication.

The tool writes to an energy-storage inverter via Modbus/TCP. Keep Modbus
restricted to trusted LAN hosts. Never expose the port to the internet.
