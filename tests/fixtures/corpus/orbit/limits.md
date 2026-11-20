# Message limits
Orbit Queue accepts messages up to 256 KB each. Larger payloads must be stored in object storage and referenced by key.

# Retention
Each queue retains messages for 14 days. After 14 days unconsumed messages are deleted.

# Visibility timeout
The default visibility timeout is 30 seconds. A consumer can extend it up to 12 hours.
