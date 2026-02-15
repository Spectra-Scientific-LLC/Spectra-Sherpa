# Data Sources & Licensing

**Version:** 1.0
**Date:** 2026-01-03
**Status:** Phase 1 (NIST implemented, HITRAN planned)

---

## 🎯 **Overview**

This document catalogs all spectral databases integrated into the platform, categorized by:
- **License type** (public domain, free academic, commercial)
- **Authentication requirements** (none, registration, API key)
- **Bundling strategy** (included in distribution vs. on-demand download)
- **Phase** (current vs. future implementation)

---

## 📚 **Free Public Spectral Databases**

### **1. NIST Chemistry WebBook** ✅ **Implemented (Phase 1)**

**Official Source:** https://webbook.nist.gov/chemistry/

**License:** Public Domain (U.S. Government work, not copyrightable)

**Access Requirements:**
- ❌ No API key required
- ❌ No user registration
- ❌ No authentication
- ✅ Polite rate limiting recommended (self-imposed: 50 requests/hour)

**Coverage:**
- **~16,000 compounds** with spectroscopic data
- **Data types:** IR, Mass Spec, UV-Vis, NMR, Raman
- **Formats:** JCAMP-DX (.jdx), GIF images
- **Resolution:** Standard (~4 cm⁻¹) and high-res (~0.125 cm⁻¹) when available

**Implementation:**
- **Backend service:** [app/services/nist.py](app/services/nist.py)
- **Download mechanism:** Direct HTTP requests to `webbook.nist.gov`
- **Caching:** Downloaded spectra saved to `data/nist_library/`
- **Deduplication:** CAS number + resolution as unique key
- **Frontend:** [NistView.vue](frontend/src/views/NistView.vue) - Search + download queue

**API Endpoints:**
```
GET  /api/v1/nist/search?query=methane          # Search by name
POST /api/v1/nist/download                       # Queue download job
GET  /api/v1/nist/library                        # List cached spectra
```

**Rate Limiting Strategy:**
```python
# Self-imposed polite crawling
NIST_RATE_LIMIT = 50  # requests per hour
NIST_DELAY_SECONDS = 72  # 3600s / 50 requests = 72s between requests

# Implemented with deque-based sliding window
rate_limiter = RateLimiter(max_requests=50, window_seconds=3600)
```

**Data Quality:**
- ✅ Peer-reviewed reference data
- ✅ Consistent format (JCAMP-DX standard)
- ⚠️ Some spectra lack metadata (temperature, pressure)
- ⚠️ Image-only data requires OCR (future enhancement)

**Use Cases:**
- Reference spectra for compound identification
- Calibration standards
- Library matching for unknown samples

**Attribution (Required in exports):**
> Data from NIST Chemistry WebBook (https://webbook.nist.gov)
> NIST Standard Reference Database Number 69

---

### **2. HITRAN Database** 🔜 **Planned (Phase 1 Q2)**

**Official Source:** https://hitran.org/

**License:** Free for academic and research use (requires citation)

**Access Levels:**

| Access Type | Registration | Features |
|-------------|--------------|----------|
| **Web Browser** | ❌ No | Browse, view individual spectra |
| **Bulk Download** | ✅ Free account | Download datasets, custom queries |
| **API Access** | ✅ Free account + key | Programmatic queries (future) |

**Coverage:**
- **High-resolution molecular spectroscopic data**
- **~50 atmospheric molecules** (H₂O, CO₂, CH₄, O₃, N₂O, CO, etc.)
- **Data types:** IR absorption, microwave, UV cross-sections
- **Resolution:** Line-by-line (ultra-high resolution)
- **Applications:** Atmospheric chemistry, remote sensing, combustion

**Implementation Plan:**

**Phase 1 (Bundled Core Set):**
- Pre-download top 50 molecules from HITRAN
- Convert to SQLite database for fast lookup
- Bundle in `data/hitran_library/hitran_core.db` (~100 MB)
- No authentication needed (data already downloaded)

**Phase 2 (Live API Integration):**
- User can optionally register HITRAN account
- Enter API key in Settings
- Query custom wavelength ranges
- Download rare molecules on-demand

**Bundled Molecules (Confirmed List):**

| Molecule | Formula | Use Case |
|----------|---------|----------|
| Water | H₂O | Atmospheric interference correction |
| Carbon Dioxide | CO₂ | Greenhouse gas monitoring |
| Methane | CH₄ | Natural gas analysis |
| Ozone | O₃ | Atmospheric chemistry |
| Nitrous Oxide | N₂O | Emissions monitoring |
| Carbon Monoxide | CO | Combustion analysis |
| Oxygen | O₂ | Atmospheric baseline |
| Nitrogen Dioxide | NO₂ | Pollution monitoring |
| Ammonia | NH₃ | Agricultural emissions |
| Formaldehyde | H₂CO | Indoor air quality |
| _(+40 more common species)_ | | |

**Database Schema:**
```sql
CREATE TABLE hitran_lines (
    id INTEGER PRIMARY KEY,
    molecule_id INTEGER,
    isotopologue_id INTEGER,
    wavenumber REAL,           -- cm⁻¹
    intensity REAL,             -- cm⁻¹/(molecule·cm⁻²)
    einstein_a REAL,            -- s⁻¹
    air_broadening REAL,        -- cm⁻¹/atm
    self_broadening REAL,       -- cm⁻¹/atm
    lower_state_energy REAL,    -- cm⁻¹
    temperature_exponent REAL,
    pressure_shift REAL
);
CREATE INDEX idx_molecule_wn ON hitran_lines(molecule_id, wavenumber);
```

**Attribution (Required):**
> High-resolution transmission molecular absorption database (HITRAN)
> Rothman et al., JQSRT (latest edition)
> https://hitran.org

---

### **3. EPA Spectral Library** 🔜 **Future (Phase 2)**

**Source:** https://speclab.epa.gov/

**License:** Public domain (U.S. EPA work)

**Coverage:**
- **~1,000 environmental pollutants**
- Focus on hazardous air pollutants (HAPs)
- Priority pollutants for regulatory compliance

**Implementation:**
- Bundle full database (~20 MB)
- Pre-indexed for fast search
- Include in `data/bundled/epa_pollutants.db`

**Use Cases:**
- Regulatory compliance (Clean Air Act)
- Environmental monitoring
- Industrial hygiene

---

### **4. Sigma-Aldrich Spectra** 🔜 **Future (Phase 2)**

**Source:** https://www.sigmaaldrich.com/spectra

**License:** Free viewing, restrictions on bulk download

**Coverage:** ~25,000 compounds (chemicals available for purchase)

**Implementation Strategy:**
- **Not bundled** (licensing restrictions)
- On-demand fetch via web scraping (with respectful rate limiting)
- Cache locally after first access
- Attribution required in exports

**Legal Considerations:**
- Terms of Service allow individual spectrum viewing
- Bulk downloads prohibited
- Must display "Data courtesy of Sigma-Aldrich"

---

## 📦 **Bundled Data Strategy**

### **What Gets Packaged with Distribution**

To enable **offline-first** usage and reduce cold-start API calls:

```
spectra-sherpa/
├── data/
│   ├── bundled/                    # Shipped with app
│   │   ├── hitran_core.db          # 100 MB - Top 50 molecules
│   │   ├── nist_samples/           # 50 MB - 100 popular compounds
│   │   │   ├── methane.jdx
│   │   │   ├── water.jdx
│   │   │   └── ...
│   │   └── epa_pollutants.db       # 20 MB - Full EPA library
│   ├── nist_library/               # User downloads (cached)
│   │   └── <cas_number>_<res>.jdx
│   └── experiments/                # User data
│       └── exp_001/
```

**Total Bundled Size:** ~170 MB (compressed to ~50 MB in installer)

---

### **Sample NIST Spectra (Top 100)**

Pre-bundle the most commonly searched compounds:

**Solvents:**
- Water, Methanol, Ethanol, Acetone, Chloroform, Dichloromethane, Hexane, Toluene

**Common Gases:**
- CO₂, CO, CH₄, N₂O, NO₂, SO₂, H₂S, NH₃

**Organic Acids:**
- Acetic acid, Formic acid, Benzoic acid, Citric acid

**Polymers/Monomers:**
- Polystyrene, Polyethylene, Styrene, Ethylene, Propylene

**Lab Chemicals:**
- Acetonitrile, Dimethyl sulfoxide (DMSO), Ethyl acetate, Isopropanol

_(Full list in `data/bundled/nist_samples/README.txt`)_

---

### **Update Mechanism**

**Phase 1 (Manual):**
- Bundled data updated with each software release (quarterly)
- User can manually refresh NIST cache by clicking "Refresh Library"

**Phase 2 (Automatic):**
- Background service checks for dataset updates weekly
- Prompts user to download updates (or auto-updates if enabled)
- Differential updates (only changed files)

**Update Metadata:**
```json
{
  "hitran_version": "2024",
  "nist_samples_updated": "2026-01-01",
  "epa_library_version": "1.0",
  "last_checked": "2026-01-03T10:30:00Z"
}
```

---

## 💰 **Premium Data Sources (Phase 2+)**

### **Wiley Spectral DB Collections** 💳 **Commercial**

**Source:** https://spectrabase.com/

**License:** Paid institutional subscription

**Cost:** $5,000 - $50,000/year (depends on institution size)

**Coverage:**
- **>2 million spectra** (largest commercial database)
- IR, NMR, Mass Spec, Raman, UV-Vis
- Includes proprietary compound libraries

**Integration Plan:**
- Requires organizational API key (encrypted storage)
- Read-only access via Wiley REST API
- Results cached locally (per license terms, 30-day TTL)
- Only available in **Paid Cloud Tier**

**API Endpoints (Future):**
```
GET /api/v1/premium/wiley/search?query=caffeine
GET /api/v1/premium/wiley/spectrum/{id}
```

**Authentication Flow:**
```
1. Admin enters Wiley API key in cloud settings
2. Key encrypted and stored in vault
3. Users search → Backend fetches from Wiley API
4. Results cached in Redis (30 days)
5. Audit log tracks usage for compliance
```

---

### **SciFinder Scholar** 💳 **Academic/Commercial**

**Source:** https://scifinder.cas.org/

**License:** Academic subscription or corporate license

**Coverage:**
- Chemical literature + spectral data
- CAS Registry integration
- Patent spectra

**Integration Plan:**
- OAuth-based authentication
- Search only (no bulk download)
- Results embedded in chat (LLM agent can query)

**Example Use Case:**
```
User: "Find all IR spectra for caffeine analogs"

LLM Agent:
1. Queries SciFinder API for caffeine substructure
2. Retrieves CAS numbers of analogs
3. Fetches IR spectra for each
4. Compares peak positions
5. Generates summary report
```

---

### **Bio-Rad KnowItAll** 💳 **Commercial**

**Source:** https://www.knowitall.com/

**License:** Per-seat perpetual license (~$3,000/seat)

**Coverage:** Large curated spectral libraries across all techniques

**Integration:**
- Import local database files (if customer already owns license)
- Read-only access (no API available)
- Compliance with license terms (no redistribution)

---

## 📊 **Data Source Comparison**

| Source | License | Auth | Coverage | Bundled | Phase | Cloud Only |
|--------|---------|------|----------|---------|-------|------------|
| **Free Public** |
| NIST WebBook | Public Domain | ❌ | 16k compounds | ✅ Samples | 1 | ❌ |
| HITRAN | Free (Academic) | ❌ Basic | 50 molecules | ✅ Full | 1 | ❌ |
| EPA Library | Public Domain | ❌ | 1k pollutants | ✅ Full | 2 | ❌ |
| Sigma-Aldrich | Free View | ❌ | 25k compounds | ❌ | 2 | ❌ |
| **Commercial** |
| Wiley SpectraBase | Paid ($$$) | ✅ Org key | 2M+ spectra | ❌ | 2 | ✅ |
| SciFinder | Paid ($$) | ✅ OAuth | Literature + spectra | ❌ | 2+ | ✅ |
| Bio-Rad KnowItAll | Paid ($$) | 🔧 Local DB | Large libraries | ❌ | 3 | ❌ |

**Legend:**
- ❌ = Not applicable / Not available
- ✅ = Available / Required
- 🔧 = Custom integration
- $ = <$10k/yr, $$ = $10k-$50k/yr, $$$ = >$50k/yr

---

## 🔒 **Licensing & Compliance**

### **Attribution Requirements**

All data sources require attribution. Display in:
1. **About Dialog** - Show all data sources used
2. **Exported Files** - Embed attribution in metadata

**Example Export Header:**
```csv
# Spectral Data Export
# Generated: 2026-01-03 10:30 PST
# Data Sources:
#   - NIST Chemistry WebBook (https://webbook.nist.gov) - Public Domain
#   - HITRAN Database (https://hitran.org) - Academic Use License
# Citation: [Auto-generated based on spectra used]
Wavenumber,Absorbance,Source
4000,0.01,NIST_CAS_74-82-8
...
```

---

### **Terms of Service Compliance**

**NIST:**
- ✅ No restrictions (public domain)
- ✅ Attribution optional but recommended
- ✅ Commercial use allowed

**HITRAN:**
- ✅ Free for academic/research
- ✅ Must cite in publications
- ⚠️ Commercial use requires contact (we're educational tool, likely OK)
- ❌ Cannot sublicense or sell raw data

**EPA:**
- ✅ Public domain (same as NIST)
- ✅ No restrictions

**Wiley/SciFinder (Future):**
- ⚠️ Requires institutional license
- ❌ Cannot redistribute spectra
- ✅ Can display in UI (read-only)
- ✅ Can cache temporarily (30 days)

---

### **Data Retention Policy**

**Free Sources:**
- Cache indefinitely (user owns downloaded data)
- User can clear cache anytime

**Premium Sources:**
- Cache for license-permitted duration (typically 30 days)
- Auto-purge expired cache entries
- Re-fetch if needed within license terms

---

## 🚀 **Implementation Roadmap**

### **Phase 1 (Current)** ✅
- [x] NIST search and download
- [x] NIST library caching
- [x] Rate limiting
- [ ] Bundle NIST samples (top 100)
- [ ] Bundle HITRAN core set

### **Phase 2 (Q2 2026)** 🔜
- [ ] EPA library integration
- [ ] HITRAN live API (optional account linking)
- [ ] Sigma-Aldrich on-demand fetching
- [ ] Automatic update checker

### **Phase 3 (Cloud Launch)** 🔜
- [ ] Wiley SpectraBase API integration
- [ ] SciFinder OAuth integration
- [ ] Premium tier feature gating
- [ ] Usage analytics for licensing compliance

---

## 📚 **User Documentation**

### **How to Use Free Data Sources**

**NIST:**
1. Navigate to "NIST Library" view
2. Search by compound name (e.g., "methane")
3. Click "Download" for standard or high-res
4. Wait for download job to complete (check queue)
5. Spectrum appears in "Downloaded Library" table
6. Click "Load" to use in Builder

**HITRAN (Bundled):**
1. Navigate to "Builder" view
2. Click "Load from HITRAN" button
3. Select molecule from dropdown (pre-loaded)
4. Spectrum loads instantly (no download needed)

---

### **How to Enable Premium Sources** (Phase 2+)

**Prerequisites:**
- Paid Cloud subscription
- Institutional license for data source

**Steps:**
1. Log in to cloud account (admin role)
2. Navigate to Settings → Premium Data
3. Enter Wiley API key (provided by your institution)
4. Test connection → "Connected ✅"
5. Users can now search Wiley database

**Billing:**
- Wiley charges your institution directly (not us)
- We track usage for your internal cost allocation
- Export usage reports monthly

---

## 🆘 **Troubleshooting**

### **NIST Download Fails**

**Error:** "Rate limit exceeded"
**Solution:** Wait 1 hour, then retry. Self-imposed limit protects NIST servers.

**Error:** "Compound not found"
**Solution:** Try different name (e.g., "H2O" → "water"). Check NIST website for exact name.

**Error:** "Network timeout"
**Solution:** NIST server may be down. Check https://webbook.nist.gov/ directly.

---

### **HITRAN Data Missing**

**Error:** "Molecule not in bundled database"
**Solution:** Only top 50 molecules bundled. Register free HITRAN account and enable live API in Settings.

---

### **Premium Source "Access Denied"**

**Error:** "Invalid Wiley API key"
**Solution:** Contact your institution's library to verify subscription status. Key may have expired.

---

## 📞 **Data Source Support Contacts**

**NIST:**
- Website: https://webbook.nist.gov/chemistry/
- Email: data@nist.gov
- Report issues: https://github.com/usnistgov/NIST-JANAF

**HITRAN:**
- Website: https://hitran.org/
- Email: hitran@cfa.harvard.edu
- Forum: https://hitran.org/forum/

**Wiley SpectraBase:**
- Support: https://spectrabase.com/support
- Sales: spectroscopy-support@wiley.com

**SciFinder:**
- CAS Support: https://www.cas.org/support
- Phone: 1-800-753-4227

---

## 🔄 **Version History**

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-03 | Initial documentation. NIST implemented, HITRAN planned. |

---

**Document Maintenance:**
- Review when adding new data sources
- Update attribution requirements if licenses change
- Update coverage statistics annually
