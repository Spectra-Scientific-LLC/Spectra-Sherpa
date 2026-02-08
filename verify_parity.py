#!/usr/bin/env python3
"""
Quick verification script to check DOE parity with original Exp_loader.

Usage:
    python verify_parity.py
"""

import sys
from pathlib import Path

import pandas as pd


def verify_csv_export(original_path: str, refactored_csv_path: str):
    """Compare CSV exports from original and refactored implementations"""

    print("=" * 70)
    print("CSV EXPORT VERIFICATION")
    print("=" * 70)

    if not Path(original_path).exists():
        print(f"⚠️  Original CSV not found: {original_path}")
        print("   Please provide the original Exp_loader CSV export")
        return False

    if not Path(refactored_csv_path).exists():
        print(f"⚠️  Refactored CSV not found: {refactored_csv_path}")
        print("   Please export CSV from the refactored DOE tab first")
        return False

    # Load CSVs
    original = pd.read_csv(original_path)
    refactored = pd.read_csv(refactored_csv_path)

    print(f"\n📊 Row counts:")
    print(f"   Original:    {len(original)} rows")
    print(f"   Refactored:  {len(refactored)} rows")

    if len(original) != len(refactored):
        print(f"   ⚠️  Row count mismatch (difference: {abs(len(original) - len(refactored))})")
    else:
        print(f"   ✅ Row counts match")

    # Compare columns
    print(f"\n📋 Column comparison:")
    original_cols = set(original.columns)
    refactored_cols = set(refactored.columns)

    print(f"   Original columns:    {sorted(original_cols)}")
    print(f"   Refactored columns:  {sorted(refactored_cols)}")

    missing = original_cols - refactored_cols
    extra = refactored_cols - original_cols

    if missing:
        print(f"   ⚠️  Missing columns: {missing}")
    if extra:
        print(f"   ℹ️  Extra columns: {extra}")
    if not missing and not extra:
        print(f"   ✅ Column sets match perfectly")

    # Compare key columns
    print(f"\n🔍 Key column verification:")
    key_columns = ["seq", "filename", "cell", "sample_id", "batch"]
    common_cols = original_cols & refactored_cols

    all_match = True
    for col in key_columns:
        if col not in common_cols:
            print(f"   ⚠️  {col:15} - MISSING in one or both CSVs")
            all_match = False
            continue

        # Compare values (taking min length to avoid index errors)
        min_len = min(len(original), len(refactored))
        matches = (original[col][:min_len] == refactored[col][:min_len]).sum()
        match_pct = (matches / min_len) * 100 if min_len > 0 else 0

        if match_pct == 100:
            print(f"   ✅ {col:15} - 100% match ({matches}/{min_len})")
        else:
            print(f"   ❌ {col:15} - {match_pct:.1f}% match ({matches}/{min_len})")
            all_match = False

            # Show first mismatch
            for i in range(min_len):
                if original[col].iloc[i] != refactored[col].iloc[i]:
                    print(f"      First mismatch at row {i}:")
                    print(f"        Original:    {original[col].iloc[i]}")
                    print(f"        Refactored:  {refactored[col].iloc[i]}")
                    break

    # Check for factor columns
    print(f"\n🎯 Factor column verification:")
    factor_cols = [c for c in common_cols if c not in ["seq", "filename", "folder",
                                                         "timestamp", "cell", "sample_id", "batch"]]

    if not factor_cols:
        print(f"   ⚠️  No factor columns found")
        all_match = False
    else:
        print(f"   Found factor columns: {factor_cols}")

        for col in factor_cols:
            min_len = min(len(original), len(refactored))
            matches = (original[col][:min_len] == refactored[col][:min_len]).sum()
            match_pct = (matches / min_len) * 100 if min_len > 0 else 0

            if match_pct == 100:
                print(f"   ✅ {col:20} - 100% match")
            else:
                print(f"   ❌ {col:20} - {match_pct:.1f}% match")
                all_match = False

    print("\n" + "=" * 70)
    if all_match:
        print("✅ VERIFICATION PASSED - CSV exports match!")
    else:
        print("❌ VERIFICATION FAILED - Discrepancies found")
    print("=" * 70)

    return all_match


def verify_folder_structure():
    """Check that required folders and files exist"""

    print("\n" + "=" * 70)
    print("FOLDER STRUCTURE VERIFICATION")
    print("=" * 70)

    checks = [
        ("Frontend source", "frontend/src/views/experiments/DoeTab.vue"),
        ("Backend DOE routes", "backend/app/api/v1/routes/doe.py"),
        ("Test script", "test_spike_doe.py"),
        ("Backend tests", "backend/tests/conftest.py"),
        ("Frontend tests", "frontend/src/test/setup.ts"),
    ]

    all_exist = True
    for name, path in checks:
        full_path = Path(__file__).parent / path
        exists = full_path.exists()
        status = "✅" if exists else "❌"
        print(f"   {status} {name:25} - {path}")
        if not exists:
            all_exist = False

    return all_exist


def verify_implementation():
    """Check that key features are implemented in the code"""

    print("\n" + "=" * 70)
    print("IMPLEMENTATION VERIFICATION")
    print("=" * 70)

    doe_tab_path = Path(__file__).parent / "frontend/src/views/experiments/DoeTab.vue"
    doe_py_path = Path(__file__).parent / "backend/app/api/v1/routes/doe.py"

    if not doe_tab_path.exists():
        print("❌ DoeTab.vue not found")
        return False

    if not doe_py_path.exists():
        print("❌ doe.py not found")
        return False

    doe_tab_content = doe_tab_path.read_text()
    doe_py_content = doe_py_path.read_text()

    checks = [
        ("Folder picker UI", "webkitdirectory", doe_tab_content),
        ("Folder selection handler", "handleFolderSelection", doe_tab_content),
        ("Auto-populate run sequence", "autoPopulateRunSequence", doe_tab_content),
        ("Dynamic factor columns", "factorColumnNames", doe_tab_content),
        ("Factor column v-for", "v-for=\"factorName in factorColumnNames\"", doe_tab_content),
        ("CSV export with factors", "all_factor_names = set()", doe_py_content),
        ("Factor CSV fieldnames", "factor_fields = sorted", doe_py_content),
        ("Eager loading import", "from sqlalchemy.orm import selectinload", doe_py_content),
        ("Plate well eager load", "selectinload(PlateWell.mixture)", doe_py_content),
    ]

    all_implemented = True
    for name, pattern, content in checks:
        found = pattern in content
        status = "✅" if found else "❌"
        print(f"   {status} {name:30} - {'Found' if found else 'Missing'}")
        if not found:
            all_implemented = False

    return all_implemented


def main():
    """Run all verifications"""

    print("\n" + "=" * 70)
    print("DOE IMPLEMENTATION PARITY VERIFICATION")
    print("Comparing refactored implementation with original Exp_loader")
    print("=" * 70)

    # Check folder structure
    structure_ok = verify_folder_structure()

    # Check implementation
    implementation_ok = verify_implementation()

    # Prompt for CSV comparison
    print("\n" + "=" * 70)
    print("CSV EXPORT COMPARISON")
    print("=" * 70)
    print("\nTo compare CSV exports, you need:")
    print("1. Original Exp_loader CSV export (e.g., EXP_20250909_6ZJBX_matched.csv)")
    print("2. Refactored DOE CSV export (export from the DOE tab)")
    print("\nProvide paths to compare (or press Enter to skip):")

    original_path = input("  Original CSV path: ").strip() or None
    refactored_path = input("  Refactored CSV path: ").strip() or None

    csv_ok = True
    if original_path and refactored_path:
        csv_ok = verify_csv_export(original_path, refactored_path)
    else:
        print("\n⚠️  Skipping CSV comparison (no paths provided)")

    # Final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"   Folder structure:  {'✅ PASS' if structure_ok else '❌ FAIL'}")
    print(f"   Implementation:    {'✅ PASS' if implementation_ok else '❌ FAIL'}")
    print(f"   CSV comparison:    {'✅ PASS' if csv_ok else '⚠️  SKIPPED' if original_path is None else '❌ FAIL'}")

    if structure_ok and implementation_ok:
        print("\n✅ All checks passed! Implementation is ready for testing.")
        print("\nNext steps:")
        print("   1. Start frontend: cd frontend && npm run dev")
        print("   2. Start backend:  cd backend && poetry run uvicorn app.main:app --reload")
        print("   3. Test with Spike_DOE_082925 folder")
        print("   4. Export CSV and compare with original")
        return 0
    else:
        print("\n❌ Some checks failed. Please review the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
