# LLM Provider Extension

The OSS package defines the AI provider contract. It does not ship a managed LLM service.

## Extension Responsibility

An extension provider can register Advisor behavior, tool access, model catalogs, and authorization policy. When no provider is registered, OSS routes should report that AI is unavailable rather than pretending a model is configured.

## Documentation Boundary

Cloud user docs explain how Advisor and Guidance feel to users. Developer docs explain the contract shape for extension authors.
