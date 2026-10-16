"""Gene extraction parsers: the base class and the registry.

Each parser lives in its own folder under app/parsers/ and is registered when the app starts.
"""
import importlib
import pkgutil

import parsers
from semantics.plugins import DescriptorError, accept_plugin, describe_parser, reject_plugin


# --- Registry for parsers ---
PARSERS = {}

def register_parser(name):
    """
    Decorator to register a parser instance under `name`.

    A parser with a valid descriptor (parsers/<name>/descriptor.ttl) becomes a gene extraction
    step with the label and ports the descriptor declares. With an invalid one, it is not a step.
    """
    def decorator(cls):
        parser = cls()
        try:
            parser.description = describe_parser(name)
            accept_plugin('parser', name)
        except DescriptorError as error:
            parser.description = None
            reject_plugin('parser', name, error)
        PARSERS[name] = parser
        return cls
    return decorator

def get_parser(name):
    return PARSERS.get(name)

# --- Main parsing function ---
def parse_file(parser, data, file, user=None, options=None):
    """
    Detect parser from `filename` extension and parse.
    Raises `RuntimeError` if no parser matches the extension.
    """
    parser = get_parser(parser)
    if not parser:
        raise RuntimeError(f'No parser registered for parser: {parser}')
    return parser.parse(data, file, user=user, options=options)

# --- Base Parser, extend this for specific file types or parsing ---
class BaseParser():
    # Step parameters, passed to parse() as options. What the parser consumes and produces is
    # declared in its descriptor.ttl.
    default_options = {}

    def read(self, file):
        """Read a stored File into the data `parse` expects. Raise ValueError if it cannot be read."""
        raise NotImplementedError

    def parse(self, data, file, user=None, options=None):
        """Parse data and persist results.

        `options` is a dict for parser-specific flags (e.g. {'complete_version': True}).
        If the parser is successful, it should return a `File` object.
        """
        raise NotImplementedError


# --- Discovery of the parsers under app/parsers/ ---
def load_parser_packages():
    """Import parsers/<name>/parser.py for every parser folder, which registers its parser."""
    for module in pkgutil.iter_modules(parsers.__path__):
        if module.ispkg:
            importlib.import_module(f'parsers.{module.name}.parser')
