import json
import re
from pathlib import Path
from typing import Iterator

from ..diagnostic import Diagnostic
from .linter import Linter
from ..replacement import Replacement


class Definition(Linter):
    """ Finds issues in definition files, such as overriding default parameters """
    def __init__(self, file: Path, settings: dict) -> None:
        super().__init__(file, settings)
        self._definitions = {}
        self._loadDefinitionFiles(file)
        self._content = self._file.read_text()
        self._loadBasePrinterSettings()

    @property
    def base_def(self):
        return "fdmextruder" if "fdmextruder" in self._definitions else "fdmprinter"

    def check(self) -> Iterator[Diagnostic]:
        if self._settings["checks"].get("diagnostic-definition-redundant-override", False):
            yield from self.checkRedefineOverride()
        # Add other which will yield Diagnostic's
        # TODO: A check to determine if the user set value is with the min and max value defined in the parent and doesn't trigger a warning
        # TODO: A check if the key exist in the first place
        # TODO: Check if the model platform exist

        yield

    def checkRedefineOverride(self) -> Iterator[Diagnostic]:
        """ Checks if definition file overrides its parents settings with the same value. """
        definition_name = list(self._definitions.keys())[0]
        definition = self._definitions[definition_name]
        if "overrides" in definition and definition_name not in ("fdmprinter", "fdmextruder"):
            for key, value_dict in definition["overrides"].items():
                is_redefined, child_key, child_value, parent = self._isDefinedInParent(key, value_dict, definition['inherits'])
                if is_redefined:
                    redefined = re.compile(r'.*(\"' + key + r'\"[\s\:\S]*?)\{[\s\S]*?\},?')
                    found = redefined.search(self._content)
                    # TODO: Figure out a way to support multiline fixes in the PR review GH Action, for now suggest no fix to ensure no ill-formed json are created
                    #  see: https://github.com/platisd/clang-tidy-pr-comments/issues/37
                    if len(found.group().splitlines()) > 1:
                        replacements = []
                    else:
                        replacements = [Replacement(
                            file = self._file,
                            offset = found.span(1)[0],
                            length = len(found.group()),
                            replacement_text = "")]

                    yield Diagnostic(
                        file = self._file,
                        diagnostic_name = "diagnostic-definition-redundant-override",
                        message = f"Overriding {key} with the same value ({child_key}: {child_value}) as defined in parent definition: {definition['inherits']}",
                        level = "Warning",
                        offset = found.span(0)[0],
                        replacements = replacements
                    )

    def _loadDefinitionFiles(self, definition_file) -> None:
        """ Loads definition file contents into self._definitions. Also load parent definition if it exists. """
        definition_name = Path(definition_file.stem).stem

        if not definition_file.exists() or definition_name in self._definitions:
            return

        # Load definition file into dictionary
        self._definitions[definition_name] = json.loads(definition_file.read_text())

        # Load parent definition if it exists
        if "inherits" in self._definitions[definition_name]:
            if self._definitions[definition_name]['inherits'] in ("fdmextruder", "fdmprinter"):
                parent_file = definition_file.parent.parent.joinpath("definitions", f"{self._definitions[definition_name]['inherits']}.def.json")
            else:
                parent_file = definition_file.parent.joinpath(f"{self._definitions[definition_name]['inherits']}.def.json")
            self._loadDefinitionFiles(parent_file)

    def _isDefinedInParent(self, key, value_dict, inherits_from):
        if "overrides" not in self._definitions[inherits_from]:
            return self._isDefinedInParent(key, value_dict, self._definitions[inherits_from]["inherits"])

        parent = self._definitions[inherits_from]["overrides"]
        if key not in self._definitions[self.base_def]["overrides"]:
            is_number = False
        else:
            is_number = self._definitions[self.base_def]["overrides"][key]["type"] in ("float", "int")
        for child_key, child_value in value_dict.items():
            if key in parent:
                if child_key in ("default_value", "value"):
                    check_values = [cv for cv in [parent[key].get("default_value", None), parent[key].get("value", None)] if cv is not None]
                else:
                    check_values = [parent[key].get(child_key, None)]
                for check_value in check_values:
                    if is_number and child_key in ("default_value", "value"):
                        try:
                            v = str(float(child_value))
                        except Exception:
                            v = child_value
                        try:
                            cv = str(float(check_value))
                        except Exception:
                            cv = check_value
                    else:
                        v = child_value
                        cv = check_value
                    if v == cv:
                        return True, child_key, child_value, parent

                if "inherits" in parent:
                    return self._isDefinedInParent(key, value_dict, parent["inherits"])
        return False, None, None, None

    def _loadBasePrinterSettings(self):
        """ TODO @Jelle please explain why this """
        settings = {}
        for k, v in self._definitions[self.base_def]["settings"].items():
            self._getSetting(k, v, settings)
        self._definitions[self.base_def] = {"overrides": settings}

    def _getSetting(self, name, setting, settings) -> None:
        if "children" in setting:
            for childname, child in setting["children"].items():
                self._getSetting(childname, child, settings)
        settings |= {name: setting}
