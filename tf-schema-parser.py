#!/usr/bin/env python3
import json
import argparse
import sys
import os
from pathlib import Path

# Optional dependency for clipboard - user can install with pip install pyperclip
try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

class TerraformSchemaParser:
    def __init__(self, schema_path):
        self.schema_path = Path(schema_path)
        self.provider = 'azurerm'  # Hardcoded for now, as per scope
        self.resources = {}
        self.data_sources = {}
        self._load_schema()

    def _load_schema(self):
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema file not found at {self.schema_path}. Run the bash script to download it.")

        with open(self.schema_path, 'r') as f:
            schema_data = json.load(f)

        provider_schema = schema_data.get('provider_schemas', {}).get(f'registry.terraform.io/hashicorp/{self.provider}')
        if not provider_schema:
            raise ValueError(f"No schema found for provider '{self.provider}' in the JSON file.")

        self.resources = provider_schema.get('resource_schemas', {})
        self.data_sources = provider_schema.get('data_source_schemas', {})

        if not self.resources and not self.data_sources:
            raise ValueError("No resources or data sources found in the schema.")

    def get_all_names(self, include_data=False):
        names = sorted(self.resources.keys())
        if include_data:
            names += sorted(self.data_sources.keys())
        return names

    def filter_names(self, query, include_data=False):
        query = query.lower()
        all_names = self.get_all_names(include_data)
        return [name for name in all_names if query in name.lower()]

    def get_schema_block(self, name):
        if name in self.resources:
            return self.resources[name].get('block', {})
        elif name in self.data_sources:
            return self.data_sources[name].get('block', {})
        return None

    def generate_hcl_template(self, name, with_descriptions=True, required_only=False, indent_level=0):
        block = self.get_schema_block(name)
        if not block:
            raise ValueError(f"No schema found for {name}")

        is_resource = name in self.resources
        block_type = "resource" if is_resource else "data"
        label = name
        instance_name = "example"

        lines = [f'{block_type} "{label}" "{instance_name}" {{']

        # Sort attributes alphabetically
        attributes = sorted(block.get('attributes', {}).items(), key=lambda x: x[0])
        for attr_name, attr_schema in attributes:
            lines.extend(self._format_attribute(attr_name, attr_schema, with_descriptions, indent_level + 1, required_only=required_only))

        # Sort block_types alphabetically
        block_types = sorted(block.get('block_types', {}).items(), key=lambda x: x[0])
        for bt_name, bt_schema in block_types:
            lines.extend(self._format_block_type(bt_name, bt_schema, with_descriptions, indent_level + 1, required_only=required_only))

        lines.append('}' * (indent_level + 1))
        return '\n'.join(lines)

    def _format_attribute(self, name, schema, with_descriptions, indent_level, required_only=False):
        if required_only and not schema.get('required', False):
            return []

        indent = '  ' * indent_level
        type_ = self._parse_type(schema.get('type'))
        required = schema.get('required', False)
        optional = schema.get('optional', False)
        computed = schema.get('computed', False)
        deprecated = schema.get('deprecated', False)
        sensitive = schema.get('sensitive', False)
        default = schema.get('default')
        description = schema.get('description', '').strip() if with_descriptions else None

        if deprecated:
            return []  # Skip deprecated for clean templates

        status = 'required' if required else ('optional' if optional else 'computed')
        comment = f"# {status}, type: {type_}"
        if sensitive:
            comment += ", sensitive"
        if default is not None:
            comment += f", default: {default}"
        if description:
            # Split long descriptions into multi-line comments
            desc_lines = [f"{indent}# {line}" for line in description.split('\n') if line.strip()]
            desc_lines.append(f"{indent}{comment}")
            comment = '\n'.join(desc_lines)
        else:
            comment = f"  {comment}"

        placeholder = self._get_placeholder(type_, attr_name=name, default=default)
        line = f"{indent}{name} = {placeholder}"
        if comment and not description:  # Inline comment if no desc
            line += comment
        else:
            lines = [comment] if comment else []
            lines.append(line)
            return lines
        return [line]

    def _format_block_type(self, name, schema, with_descriptions, indent_level, required_only=False):
        min_items = schema.get('min_items', 0)
        if required_only and min_items == 0:
            return []

        indent = '  ' * indent_level
        nesting = schema.get('nesting_mode', 'single')
        max_items = schema.get('max_items', None)
        description = schema.get('description', '').strip() if with_descriptions else None

        block = schema.get('block', {})
        sub_attributes = sorted(block.get('attributes', {}).items(), key=lambda x: x[0])
        sub_block_types = sorted(block.get('block_types', {}).items(), key=lambda x: x[0])

        lines = []

        comment = f"# nesting: {nesting}, min: {min_items}"
        if max_items is not None:
            comment += f", max: {max_items}"
        if description:
            desc_lines = [f"{indent}# {line}" for line in description.split('\n') if line.strip()]
            desc_lines.append(f"{indent}{comment}")
            lines.extend(desc_lines)
        else:
            lines.append(f"{indent}# {comment}")

        if nesting == 'single':
            lines.append(f"{indent}{name} {{")
            for attr_name, attr_schema in sub_attributes:
                lines.extend(self._format_attribute(attr_name, attr_schema, with_descriptions, indent_level + 1, required_only=required_only))
            for bt_name, bt_schema in sub_block_types:
                lines.extend(self._format_block_type(bt_name, bt_schema, with_descriptions, indent_level + 1, required_only=required_only))
            lines.append(f"{indent}}}")
        elif nesting in ('list', 'set'):
            repeat_comment = f"{indent}# Repeat this block as needed (min: {min_items}"
            if max_items:
                repeat_comment += f", max: {max_items}"
            repeat_comment += ")"
            lines.append(repeat_comment)
            if min_items > 0:
                for _ in range(min_items):
                    lines.append(f"{indent}{name} {{")
                    for attr_name, attr_schema in sub_attributes:
                        lines.extend(self._format_attribute(attr_name, attr_schema, with_descriptions, indent_level + 1, required_only=required_only))
                    for bt_name, bt_schema in sub_block_types:
                        lines.extend(self._format_block_type(bt_name, bt_schema, with_descriptions, indent_level + 1, required_only=required_only))
                    lines.append(f"{indent}}}")
            else:
                lines.append(f"{indent}{name} {{  # optional, uncomment and fill if needed")
                lines.append(f"{indent}  # ...")
                lines.append(f"{indent}}}")
        elif nesting == 'map':
            lines.append(f"{indent}{name} = {{  # key = value syntax, repeat as needed")
            lines.append(f"{indent}  example_key {{")
            for attr_name, attr_schema in sub_attributes:
                lines.extend(self._format_attribute(attr_name, attr_schema, with_descriptions, indent_level + 2, required_only=required_only))
            for bt_name, bt_schema in sub_block_types:
                lines.extend(self._format_block_type(bt_name, bt_schema, with_descriptions, indent_level + 2, required_only=required_only))
            lines.append(f"{indent}  }}")
            lines.append(f"{indent}}}")

        return lines

    def _parse_type(self, type_):
        if isinstance(type_, str):
            return type_
        elif isinstance(type_, list):
            if type_[0] in ('list', 'set', 'map'):
                return f"{type_[0]}({self._parse_type(type_[1])})"
            elif type_[0] == 'object':
                return 'object({...})'  # Simplified
            elif type_[0] == 'tuple':
                return 'tuple([...])'
        return 'unknown'

    def _get_placeholder(self, type_, attr_name=None, default=None):
        if default is not None:
            return json.dumps(default)
        if attr_name:
            if attr_name.endswith('_name'):
                resource_type = attr_name[:-5]  # remove '_name'
                return f'azurerm_{resource_type}.example.name'
            elif attr_name.endswith('_id'):
                resource_type = attr_name[:-3]  # remove '_id'
                return f'azurerm_{resource_type}.example.id'
        if type_ == 'string':
            return '""'
        elif type_ == 'bool':
            return 'false'
        elif type_ == 'number':
            return '0'
        elif type_.startswith('list') or type_.startswith('set'):
            return '[]'
        elif type_.startswith('map') or type_.startswith('object'):
            return '{}'
        elif type_.startswith('tuple'):
            return '[]'
        return 'null'

def interactive_mode(parser):
    include_data = False  # For now, focus on resources; can add prompt later
    while True:
        query = input("\nEnter search query (or 'q' to quit, 'data' to toggle data sources): ").strip()
        if query.lower() == 'q':
            break
        elif query.lower() == 'data':
            include_data = not include_data
            print(f"Data sources {'included' if include_data else 'excluded'}.")
            continue

        matches = parser.filter_names(query, include_data)
        if not matches:
            print("No matches found. Try again.")
            continue

        print("\nMatches:")
        for i, name in enumerate(matches, 1):
            print(f"{i}. {name}")

        try:
            selection = int(input("Select number: "))
            if 1 <= selection <= len(matches):
                selected = matches[selection - 1]
                full_template = parser.generate_hcl_template(selected, required_only=False)
                required_template = parser.generate_hcl_template(selected, required_only=True)
                print("\nGenerated HCL Template (Full Version):")
                print(full_template)

                # Export options
                action = input("\nWhat do you want to do? (p: print again, f: save to file, c: copy required only, o: copy full version, b: back): ").lower()
                if action == 'f':
                    file_path = input("Enter file path (e.g., resource.tf): ")
                    with open(file_path, 'w') as f:
                        f.write(full_template)
                    print(f"Saved full version to {file_path}")
                elif action == 'c' and HAS_CLIPBOARD:
                    pyperclip.copy(required_template)
                    print("Copied required-only version to clipboard.")
                elif action == 'o' and HAS_CLIPBOARD:
                    pyperclip.copy(full_template)
                    print("Copied full version to clipboard.")
                elif action in ('c', 'o') and not HAS_CLIPBOARD:
                    print("pyperclip not installed. Install with 'pip install pyperclip' for clipboard support.")
                elif action == 'p':
                    print(full_template)
            else:
                print("Invalid selection.")
        except ValueError:
            print("Invalid input. Enter a number.")

def main():
    arg_parser = argparse.ArgumentParser(description="Terraform Schema Explorer CLI")
    arg_parser.add_argument('--schema-path', default='/home/ubuntu/Downloads/terraform/schema/azurerm_schema.json',
                            help='Path to the schema JSON file')
    arg_parser.add_argument('--resource', help='Directly generate for a specific resource (non-interactive)')
    arg_parser.add_argument('--output', help='Output file path for non-interactive mode')
    args = arg_parser.parse_args()

    try:
        schema_parser = TerraformSchemaParser(args.schema_path)

        if args.resource:
            template = schema_parser.generate_hcl_template(args.resource)
            if args.output:
                with open(args.output, 'w') as f:
                    f.write(template)
                print(f"Saved to {args.output}")
            else:
                print(template)
        else:
            print("Entering interactive mode. Search for resources by partial name.")
            if not HAS_CLIPBOARD:
                print("Note: Install pyperclip for clipboard support: pip install pyperclip")
            interactive_mode(schema_parser)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
