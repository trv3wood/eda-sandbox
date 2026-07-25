# Packet Engine Fixture

Writing START launches processing on one configured channel. Packets contain a
16-bit byte length and payload. The engine queues ingress data, parses the
header, updates a checksum, arbitrates between channels, and queues output.
Zero-length packets are rejected. Completion sets DONE and raises IRQ when
enabled. This Markdown file documents the synthetic fixture; production input
uses DOCX.

