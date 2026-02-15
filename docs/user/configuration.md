# Configuration

SpectraSherpa works out-of-the-box with zero configuration. However, you can customize data storage and enable optional AI features.

## Data Storage
By default, all your data is stored in your home directory:
```
~/.spectra_sherpa/
├── spectra_platform.db    # Your local database
├── experiments/           # Uploaded files and results
├── calibrations/          # Saved models
└── nist_library/          # Downloaded reference spectra
```

To use a different location (e.g., an external drive), use the `--data-dir` flag:
```bash
spectra-sherpa --data-dir /Volumes/ExternalDrive/SherpaData
```

## Enabling AI Features (Optional)
To use the **Workflow Assistant** (LLM) or **NIST Library Search**, you need to enable network access and provide API keys.

1.  Create a `.env` file in the folder where you run `spectra-sherpa`:

    ```bash
    # .env
    EGRESS_ENABLED=true
    
    # Add your keys (only one is needed)
    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=sk-ant-...
    DEEPSEEK_API_KEY=sk-...
    ```

2.  Restart the application.

3.  Alternatively, you can add keys directly in the UI under **Settings > API Keys**.

> **Privacy Note:** In Local Mode, your API keys are stored encrypted on your machine. Data is only sent to the AI provider when you explicitly use an AI feature (like "Ask Sherpa").
