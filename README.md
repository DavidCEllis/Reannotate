# Reannotate #

This library acts as an extension to the new deferred annotations that arrived as part of PEP 649/749
in Python 3.14.

This library is intended to help for tools that need to retrieve annotations and combine them
to create new `__annotate__` dunctions.

To this end it introduces a new `DeferredAnnotation` class, two helper functions for getting deferred
annotations and a `ReAnnotate` class to replace `__annotate__` on existing annotated objects.

## Usage ##

