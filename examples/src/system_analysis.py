import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft7Validator

from system_interpreter import derive_assessment
from system_signals import calculate_all_signals

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = BASE_DIR / "schema" / "system_case.schema.json"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def load_system_case(path):
    return load_json(path)


def load_schema(schema_path):
    return load_json(schema_path)


def validate_case(case, schema):
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(case), key=lambda e: e.path)

    if errors:
        formatted_errors = []
        for error in errors:
            location = ".".join(str(part) for part in error.path) or "root"
            formatted_errors.append(f"- {location}: {error.message}")
        return False, formatted_errors

    return True, []


def build_output(
    case,
    source_file=None,
    use_computed_signals=True,
    use_computed_assessment=True,
):
    signals = calculate_all_signals(case) if use_computed_signals else case["signals"]
    assessment = (
        derive_assessment(signals) if use_computed_assessment else case["assessment"]
    )

    return {
        "source_file": str(source_file) if source_file else None,
        "system_reference": case.get("system_reference"),
        "title": case.get("title"),
        "system_type": case.get("system_type"),
        "domain": case.get("domain"),
        "declared_purpose": case.get("declared_purpose"),
        "signals": signals,
        "assessment": assessment,
    }
def generate_run_id():
    now = datetime.now(timezone.utc)
    return f"system-analysis-{now.strftime('%Y-%m-%d-%H%M%S')}"

def generate_run_id():
    now = datetime.now(timezone.utc)
    return f"system-analysis-{now.strftime('%Y-%m-%d-%H%M%S')}"

def build_run_metadata(args, input_path, schema_path, case_count):
    return {
        "run_id": generate_run_id(),
        "run_id": generate_run_id(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "system_analysis",
        "input_path": str(input_path),
        "schema_path": str(schema_path) if schema_path else None,
        "batch": bool(args.batch),
        "validation_enabled": not args.no_validate,
        "computed_signals": not args.raw_signals,
        "computed_assessment": not args.raw_assessment,
        "case_count": case_count,
    }


def print_summary(output):
    print("\nSystem Loaded — System Analysis Mode\n")
    if output.get("source_file"):
        print(f"Source File: {output['source_file']}")
    print(f"System: {output['title']}")
    print(f"Type: {output['system_type']}")
    print(f"Declared Purpose: {output['declared_purpose']}\n")

    print("Signals:")
    for key, value in output["signals"].items():
        print(f"- {key}: {value}")

    print("\nAssessment:")
    print(f"Posture: {output['assessment']['system_posture']}")
    print(f"Finding: {output['assessment']['structural_finding']}")
    print(f"Interpretation: {output['assessment']['interpretation']}")
    print("-" * 60)


def get_json_files(input_path):
    if input_path.is_file():
        return [input_path]

    if input_path.is_dir():
        return sorted([path for path in input_path.glob("*.json") if path.is_file()])

    return []


def process_case_file(
    case_path,
    schema,
    skip_validation=False,
    use_computed_signals=True,
    use_computed_assessment=True,
):
    case = load_system_case(str(case_path))

    if not skip_validation:
        is_valid, validation_errors = validate_case(case, schema)
        if not is_valid:
            return {
                "source_file": str(case_path),
                "error": "validation_failed",
                "validation_errors": validation_errors,
            }

    return build_output(
        case,
        source_file=case_path,
        use_computed_signals=use_computed_signals,
        use_computed_assessment=use_computed_assessment,
    )


def print_validation_error(result):
    print("\nValidation Error — System Analysis Mode\n")
    print(f"Input file: {result['source_file']}\n")
    print("The system case did not pass schema validation:")
    for err in result["validation_errors"]:
        print(err)
    print("-" * 60)


def format_markdown_result(result):
    if result.get("error") == "validation_failed":
        lines = [
            f"## {result.get('source_file', 'Unknown file')}",
            "",
            "**Validation Error**",
            "",
            "The system case did not pass schema validation:",
            "",
        ]
        for err in result.get("validation_errors", []):
            lines.append(f"- {err}")
        lines.append("")
        return "\n".join(lines)

    lines = [
        f"## {result.get('title', 'Untitled System')}",
        "",
        f"- **Source File:** {result.get('source_file')}",
        f"- **System Reference:** {result.get('system_reference')}",
        f"- **System Type:** {result.get('system_type')}",
        f"- **Domain:** {result.get('domain')}",
        f"- **Declared Purpose:** {result.get('declared_purpose')}",
        "",
        "### Signals",
        "",
    ]

    for key, value in result.get("signals", {}).items():
        lines.append(f"- **{key}:** {value}")

    assessment = result.get("assessment", {})
    lines.extend(
        [
            "",
            "### Assessment",
            "",
            f"- **Posture:** {assessment.get('system_posture')}",
            f"- **Finding:** {assessment.get('structural_finding')}",
            f"- **Interpretation:** {assessment.get('interpretation')}",
            "",
        ]
    )

    return "\n".join(lines)


def export_markdown(results, export_path, metadata=None):
    export_path = Path(export_path)
    export_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(results, dict):
        results = [results]

    lines = [
        "# System Analysis Report",
        "",
    ]

    if metadata:
        lines.extend(
            [
                "## Run Metadata",
                "",
                f"- **Run ID:** {metadata.get('run_id')}",
                f"- **Generated At:** {metadata.get('generated_at')}",
                f"- **Mode:** {metadata.get('mode')}",
                f"- **Input Path:** {metadata.get('input_path')}",
                f"- **Schema Path:** {metadata.get('schema_path')}",
                f"- **Batch Mode:** {metadata.get('batch')}",
                f"- **Validation Enabled:** {metadata.get('validation_enabled')}",
                f"- **Computed Signals:** {metadata.get('computed_signals')}",
                f"- **Computed Assessment:** {metadata.get('computed_assessment')}",
                f"- **Case Count:** {metadata.get('case_count')}",
                "",
            ]
        )

    for result in results:
        lines.append(format_markdown_result(result))

    with open(export_path, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Civic Decision Engine — System Analysis Mode"
    )
    parser.add_argument(
        "input",
        help="Path to a system case JSON file or a folder of system case JSON files",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA),
        help="Path to the system case schema JSON file",
    )
    parser.add_argument(
        "--raw-signals",
        action="store_true",
        help="Use signals stored in the JSON instead of computing them",
    )
    parser.add_argument(
        "--raw-assessment",
        action="store_true",
        help="Use assessment stored in the JSON instead of deriving it",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip schema validation",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all JSON files in a directory",
    )
    parser.add_argument(
        "--export",
        help="Path to save output JSON file",
    )
    parser.add_argument(
        "--export-md",
        help="Path to save output Markdown report",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    schema_path = Path(args.schema)

    if not input_path.exists():
        print(f"Error: input not found -> {input_path}")
        return

    if not args.no_validate and not schema_path.exists():
        print(f"Error: schema file not found -> {schema_path}")
        return

    schema = None if args.no_validate else load_schema(str(schema_path))

    if args.batch:
        if not input_path.is_dir():
            print(f"Error: --batch requires a directory -> {input_path}")
            return

        case_files = get_json_files(input_path)

        if not case_files:
            print(f"Error: no JSON files found in directory -> {input_path}")
            return

        results = []
        for case_file in case_files:
            result = process_case_file(
                case_file,
                schema=schema,
                skip_validation=args.no_validate,
                use_computed_signals=not args.raw_signals,
                use_computed_assessment=not args.raw_assessment,
            )
            results.append(result)

        metadata = build_run_metadata(
            args=args,
            input_path=input_path,
            schema_path=schema_path if not args.no_validate else None,
            case_count=len(results),
        )

        if args.export:
            export_path = Path(args.export)
            export_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_metadata": metadata,
                "results": results,
            }
            with open(export_path, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"\nExported results -> {export_path}")

        if args.export_md:
            export_markdown(results, args.export_md, metadata=metadata)
            print(f"Exported Markdown report -> {args.export_md}")

        if args.json:
            print(
                json.dumps(
                    {
                        "run_metadata": metadata,
                        "results": results,
                    },
                    indent=2,
                )
            )
        else:
            for result in results:
                if result.get("error") == "validation_failed":
                    print_validation_error(result)
                else:
                    print_summary(result)

        return

    if input_path.is_dir():
        print(f"Error: directory input requires --batch -> {input_path}")
        return

    result = process_case_file(
        input_path,
        schema=schema,
        skip_validation=args.no_validate,
        use_computed_signals=not args.raw_signals,
        use_computed_assessment=not args.raw_assessment,
    )

    if result.get("error") == "validation_failed":
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_validation_error(result)
        return

    metadata = build_run_metadata(
        args=args,
        input_path=input_path,
        schema_path=schema_path if not args.no_validate else None,
        case_count=1,
    )

    if args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_metadata": metadata,
            "results": [result],
        }
        with open(export_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\nExported result -> {export_path}")

    if args.export_md:
        export_markdown(result, args.export_md, metadata=metadata)
        print(f"Exported Markdown report -> {args.export_md}")

    if args.json:
        print(
            json.dumps(
                {
                    "run_metadata": metadata,
                    "results": [result],
                },
                indent=2,
            )
        )
    else:
        print_summary(result)


if __name__ == "__main__":
    main()
