#!/usr/bin/env python3
"""Test script to verify DOE matching with Spike_DOE_082925 data"""

import requests
import json
import csv
from pathlib import Path

BASE_URL = "http://localhost:9000/api/v1"
API_KEY = "default-local-key"
HEADERS = {"X-API-Key": API_KEY}

DATA_PATH = Path("/Users/fe2val/Documents/Spectra Scientific/Component_code/Original/data/Spike_DOE_082925")
ORIGINAL_CSV = DATA_PATH / "EXP_20250909_6ZJBX_matched.csv"

def create_experiment():
    """Create a test experiment"""
    response = requests.post(
        f"{BASE_URL}/experiments",
        json={
            "name": "Spike_DOE_Test",
            "description": "Test of DOE matching with Spike_DOE_082925 data"
        },
        headers=HEADERS
    )
    response.raise_for_status()
    exp_id = response.json()["id"]
    print(f"✓ Created experiment ID: {exp_id}")
    return exp_id

def import_samples(exp_id):
    """Import sample database"""
    # From XML, we have these samples
    samples_csv = """sample_id,name,type,brand,cas_number,active,notes
ACL2,Lavender Oil ACL2,Standard,,,true,
BORNEOL1,Borneol,Standard,,,true,
CAMPHOR1,Camphor,Standard,,,true,
CINEOL1,1-8-Cineole,Standard,,,true,
LINALOOL2,Linalool,Standard,,,true,
LINA_ACT1,Linalyl Acetate,Standard,,,true,
CAL1,Calibration Standard,Standard,,,true,
X,Blank,Solvent,,,true,"""

    response = requests.post(
        f"{BASE_URL}/experiments/{exp_id}/doe/samples/import",
        json={"csv_data": samples_csv},
        headers=HEADERS
    )
    response.raise_for_status()
    samples = response.json()
    print(f"✓ Imported {len(samples)} samples")
    return samples

def create_mixtures(exp_id, samples):
    """Create mixtures from XML"""
    sample_lookup = {s["sample_id"]: s["id"] for s in samples}

    mixtures_config = [
        # Pure samples
        ("ACL2", "ACL2", "volume", [("ACL2", 1.0, "mL")]),
        ("CAL1", "CAL1", "volume", [("CAL1", 1.0, "mL")]),
        ("CAMPHOR1", "CAMPHOR1", "volume", [("CAMPHOR1", 1.0, "mL")]),
        ("BORNEOL1", "BORNEOL1", "volume", [("BORNEOL1", 1.0, "mL")]),
        ("CINEOL1", "CINEOL1", "volume", [("CINEOL1", 1.0, "mL")]),
        ("LINA_ACT1", "LINA_ACT1", "volume", [("LINA_ACT1", 1.0, "mL")]),
        ("LINALOOL2", "LINALOOL2", "volume", [("LINALOOL2", 1.0, "mL")]),
        ("X", "X", "volume", [("X", 1.0, "mL")]),

        # Mixtures
        ("ACL+Borneol mixture 5%", "ACL+Borneol mixture 5%", "mass", [("BORNEOL1", 0.4, "g"), ("ACL2", 0.02, "g")]),
        ("ACL+Borneol mixture 2.5%", "ACL+Borneol mixture 2.5%", "mass", [("BORNEOL1", 0.4, "g"), ("ACL2", 0.01, "g")]),
        ("ACL+Camphor mixture 2.5%", "ACL+Camphor mixture 2.5%", "mass", [("ACL2", 0.4, "g"), ("CAMPHOR1", 0.01, "g")]),
        ("ACL+Camphor mixture 5%", "ACL+Camphor mixture 5%", "mass", [("ACL2", 0.4, "g"), ("CAMPHOR1", 0.02, "g")]),
        ("ACL+25% Cineole", "ACL+25% Cineole", "volume", [("CINEOL1", 25.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+20% Cineole", "ACL+20% Cineole", "volume", [("CINEOL1", 20.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+15% Cineole", "ACL+15% Cineole", "volume", [("CINEOL1", 15.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+10% Cineole", "ACL+10% Cineole", "volume", [("CINEOL1", 10.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+5% Cineole", "ACL+5% Cineole", "volume", [("CINEOL1", 5.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+5% Linalyl Acetate", "ACL+5% Linalyl Acetate", "volume", [("LINA_ACT1", 5.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+10% Linalyl Acetate", "ACL+10% Linalyl Acetate", "volume", [("LINA_ACT1", 10.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+15% Linalyl Acetate", "ACL+15% Linalyl Acetate", "volume", [("LINA_ACT1", 15.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+20% Linalyl Acetate", "ACL+20% Linalyl Acetate", "volume", [("LINA_ACT1", 20.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+25% Linalyl Acetate", "ACL+25% Linalyl Acetate", "volume", [("LINA_ACT1", 25.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+25% Linalool", "ACL+25% Linalool", "volume", [("LINALOOL2", 25.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+20% Linalool", "ACL+20% Linalool", "volume", [("LINALOOL2", 20.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+15% Linalool", "ACL+15% Linalool", "volume", [("LINALOOL2", 15.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+10% Linalool", "ACL+10% Linalool", "volume", [("LINALOOL2", 10.0, "mL"), ("ACL2", 100.0, "mL")]),
        ("ACL+5% Linalool", "ACL+5% Linalool", "volume", [("LINALOOL2", 5.0, "mL"), ("ACL2", 100.0, "mL")]),
    ]

    mixtures = []
    for mixture_id, name, basis, components in mixtures_config:
        components_list = [
            {"sample_id": sample_lookup[comp[0]], "amount": comp[1], "unit": comp[2]}
            for comp in components
        ]

        response = requests.post(
            f"{BASE_URL}/experiments/{exp_id}/doe/mixtures",
            json={
                "mixture_id": mixture_id,
                "name": name,
                "basis": basis,
                "components": components_list
            },
            headers=HEADERS
        )
        response.raise_for_status()
        mixtures.append(response.json())

    print(f"✓ Created {len(mixtures)} mixtures")
    return mixtures

def setup_plate_map(exp_id, mixtures):
    """Set up 96-well plate map"""
    mixture_lookup = {m["mixture_id"]: m["id"] for m in mixtures}

    # From XML PlateMap
    plate_assignments = {
        "A5": "X", "A6": "X", "A7": "X", "A8": "X", "A9": "X",
        "B5": "ACL2", "B6": "ACL2", "B7": "ACL2", "B8": "ACL2", "B9": "ACL2",
        "C5": "CAL1", "C6": "CAL1", "C7": "CINEOL1", "C8": "LINA_ACT1", "C9": "LINALOOL2",
        "D5": "CAL1", "D6": "CAL1", "D7": "ACL+25% Cineole", "D8": "ACL+25% Linalyl Acetate", "D9": "ACL+25% Linalool",
        "E5": "CAL1", "E6": "CAL1", "E7": "ACL+20% Cineole", "E8": "ACL+20% Linalyl Acetate", "E9": "ACL+20% Linalool",
        "F5": "CAMPHOR1", "F6": "BORNEOL1", "F7": "ACL+15% Cineole", "F8": "ACL+15% Linalyl Acetate", "F9": "ACL+15% Linalool",
        "G5": "ACL+Camphor mixture 2.5%", "G6": "ACL+Borneol mixture 2.5%", "G7": "ACL+10% Cineole", "G8": "ACL+10% Linalyl Acetate", "G9": "ACL+10% Linalool",
        "H5": "ACL+Camphor mixture 5%", "H6": "ACL+Borneol mixture 5%", "H7": "ACL+5% Cineole", "H8": "ACL+5% Linalyl Acetate", "H9": "ACL+5% Linalool",
    }

    wells = [
        {"well_position": pos, "mixture_id": mixture_lookup[mix_id]}
        for pos, mix_id in plate_assignments.items()
    ]

    response = requests.post(
        f"{BASE_URL}/experiments/{exp_id}/doe/plate-map",
        json={"wells": wells},
        headers=HEADERS
    )
    response.raise_for_status()
    print(f"✓ Set up plate map with {len(wells)} wells")

def create_factor_and_run_sequence(exp_id):
    """Create Defocus factor and run sequence"""
    # Create factor
    response = requests.post(
        f"{BASE_URL}/experiments/{exp_id}/doe/factors",
        json={
            "name": "Defocus",
            "scope": "method",
            "type": "numeric",
            "unit": "mm",
            "levels": None
        },
        headers=HEADERS
    )
    response.raise_for_status()
    factor = response.json()
    factor_id = factor["id"]
    print(f"✓ Created factor 'Defocus [mm]'")

    # Create run levels - send all at once in the format expected by RunSequenceRequest
    run_levels_data = [
        {"factor_definition_id": factor_id, "path": "08-29-2025_@05-19-55", "batch": 1, "level_value": "94", "file_count": 40, "sequence_order": 0},
        {"factor_definition_id": factor_id, "path": "08-29-2025_@05-39-11", "batch": 2, "level_value": "93", "file_count": 40, "sequence_order": 1},
        {"factor_definition_id": factor_id, "path": "08-29-2025_@05-57-09", "batch": 3, "level_value": "95", "file_count": 40, "sequence_order": 2},
    ]

    response = requests.post(
        f"{BASE_URL}/experiments/{exp_id}/doe/run-sequence",
        json={"levels": run_levels_data},
        headers=HEADERS
    )
    response.raise_for_status()
    print(f"✓ Created run sequence with 3 levels")

def match_acquisitions(exp_id):
    """Match acquisition files from the 3 folders"""

    # Get file lists from the 3 batch folders
    folders = []
    folder_paths = [
        "08-29-2025_@05-19-55",
        "08-29-2025_@05-39-11",
        "08-29-2025_@05-57-09"
    ]

    for idx, folder_name in enumerate(folder_paths):
        folder_path = DATA_PATH / folder_name
        files = sorted([f.name for f in folder_path.glob("Spectrum_*.csv")])
        folders.append({
            "folder_path": folder_name,
            "batch_number": idx + 1,
            "file_list": files
        })

    # Match with scan path settings
    payload = {
        "folders": folders,
        "first_cell": "A5",
        "scan_orientation": "serpentine_column",
        "seq_offset": 0,  # Global index starts at 0, +1 gives seq starting at 1
        "use_plate_map": True,
        "use_run_sequence": True
    }

    response = requests.post(
        f"{BASE_URL}/experiments/{exp_id}/doe/match-acquisitions",
        json=payload,
        headers=HEADERS
    )
    response.raise_for_status()
    matched = response.json()
    print(f"✓ Matched {len(matched)} acquisitions")
    return matched

def export_csv(exp_id):
    """Export matched acquisitions to CSV"""
    response = requests.get(
        f"{BASE_URL}/experiments/{exp_id}/doe/export/csv",
        headers=HEADERS
    )
    response.raise_for_status()
    csv_content = response.text

    # Save to file
    output_path = Path("/tmp/refactored_matched.csv")
    output_path.write_text(csv_content)
    print(f"✓ Exported CSV to {output_path}")
    return csv_content

def compare_results():
    """Compare the refactored output with original"""
    original_path = ORIGINAL_CSV
    refactored_path = Path("/tmp/refactored_matched.csv")

    # Read both CSVs
    with open(original_path) as f:
        original_reader = csv.DictReader(f)
        original_rows = list(original_reader)

    with open(refactored_path) as f:
        refactored_reader = csv.DictReader(f)
        refactored_rows = list(refactored_reader)

    print(f"\n--- Comparison ---")
    print(f"Original rows: {len(original_rows)}")
    print(f"Refactored rows: {len(refactored_rows)}")

    # Compare first few rows
    # Note: Original CSV has bugs - seq restarts per batch, all Batch=1
    # We compare: filename, cell, sample_id, Defocus [mm]
    print(f"\nFirst 10 rows comparison (key fields only):")
    mismatches = 0
    for i in range(min(10, len(original_rows), len(refactored_rows))):
        orig = original_rows[i]
        refac = refactored_rows[i]

        # Check if key values match
        file_match = orig.get('# File') == refac.get('filename')
        cell_match = orig.get('Cell') == refac.get('cell')
        sample_match = orig.get('Sample ID') == refac.get('sample_id')
        defocus_match = orig.get('Defocus [mm]') == refac.get('Defocus [mm]')

        all_match = file_match and cell_match and sample_match and defocus_match

        if not all_match:
            mismatches += 1
            print(f"\nRow {i+1}: {'✓' if all_match else '✗'}")
            print(f"  File:    {'✓' if file_match else '✗'} {orig.get('# File')} vs {refac.get('filename')}")
            print(f"  Cell:    {'✓' if cell_match else '✗'} {orig.get('Cell')} vs {refac.get('cell')}")
            print(f"  Sample:  {'✓' if sample_match else '✗'} {orig.get('Sample ID')} vs {refac.get('sample_id')}")
            print(f"  Defocus: {'✓' if defocus_match else '✗'} {orig.get('Defocus [mm]')} vs {refac.get('Defocus [mm]')}")

    if mismatches == 0:
        print("  All first 10 rows match! ✓")
    else:
        print(f"\n{mismatches} mismatches in first 10 rows")

def main():
    """Run the complete test"""
    print("=" * 60)
    print("Testing Refactored DOE with Spike_DOE_082925 Data")
    print("=" * 60)

    try:
        # Step 1: Create experiment
        exp_id = create_experiment()

        # Step 2: Import samples
        samples = import_samples(exp_id)

        # Step 3: Create mixtures
        mixtures = create_mixtures(exp_id, samples)

        # Step 4: Setup plate map
        setup_plate_map(exp_id, mixtures)

        # Step 5: Create factor and run sequence
        create_factor_and_run_sequence(exp_id)

        # Step 6: Match acquisitions
        matched = match_acquisitions(exp_id)

        # Step 7: Export CSV
        export_csv(exp_id)

        # Step 8: Compare results
        compare_results()

        print("\n" + "=" * 60)
        print("✓ Test completed successfully!")
        print("=" * 60)

    except requests.exceptions.RequestException as e:
        print(f"\n✗ Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())
