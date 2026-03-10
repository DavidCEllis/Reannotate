# Reannotate #

This library acts as an extension to the new deferred annotations that arrived as part of PEP-649/749
in Python 3.14.

Its main purpose is to make it as easy to modify and create `__annotate__` functions as it was to modify
the `__annotations__` dictionary in earlier versions of Python.

It also makes it easy to retrieve annotations and evaluate them individually.

Unlike `Format.FORWARDREF`, `get_deferred_annotations` will always return `DeferredAnnotation` objects as the values
of the annotations dictionary.

## Retrieving deferred annotations ##

`get_deferred_annotations` is provided to retrieve deferred annotations from an annotated object:

```python
from reannotate import get_deferred_annotations

class Example:
    a: int
    b: list[unknown]
    c: str | undefined

annos = get_deferred_annotations(Example)

print(annos)
```

```python
{'a': DeferredAnnotation('int'), 'b': DeferredAnnotation('list[unknown]'), 'c': DeferredAnnotation('str | undefined')}
```

To use the `DeferredAnnotation` objects, they have an `.evaluate()` method that supports the standard `annotationlib` formats:

```python
from annotationlib import Format

print(annos['a'].evaluate(format=Format.VALUE))
print(annos['b'].evaluate(format=Format.FORWARDREF))
print(annos['c'].evaluate(format=Format.STRING))
```

```python
<class 'int'>
list[ForwardRef('unknown', is_class=True, owner=<class '__main__.Example'>)]
str | undefined
```

If a value is defined at a later point, the annotation can then be evaluated fully.

```python
unknown = float

print(annos['b'].evaluate())
print(annos['b'].is_resolved)  # If a DeferredAnnotation has been fully evaluated, this is set to True
```

```python
list[float]
True
```

## Creating a new `__annotate__` callable ##

Instances of the `ReAnnotate` class are intended to act as `__annotate__` callables.

```python
from annotationlib import call_annotate_function, Format
from reannotate import get_deferred_annotations, ReAnnotate

class Example:
    a: int
    b: list[undefined]

annos = get_deferred_annotations(Example)

new_annos = ReAnnotate(annos)

print(call_annotate_function(new_annos, format=Format.FORWARDREF))
```

```python
{'a': <class 'int'>, 'b': list[ForwardRef('undefined', is_class=True, owner=<class '__main__.Example'>)]}
```

## Use case examples ##

### Adding fields automatically to a dataclass ###

With the new annotations in Python 3.14 it is no longer always possible to retrieve `__annotations__`.
To correctly handle inserting a field into a dataclass it is necessary to create a new `__annotate__` function.

Using `get_deferred_annotations` and `ReAnnotate`, this is now as straight forward as it was prior to Python 3.14.

```python
from annotationlib import get_annotations, Format
from dataclasses import dataclass, field
from functools import wraps

from reannotate import get_deferred_annotations, ReAnnotate

def debug_dataclass(cls):
    # Gets all annotations in an unevaluated format
    annos = get_deferred_annotations(cls)

    # Standard objects can be provided and will be converted to `DeferredAnnotation` values
    annos |= {"_used_kwargs": dict[str, object]}

    # ReAnnotate instances are callables that replace the `__annotate__` function
    cls.__annotate__ = ReAnnotate(annos)
    cls._used_kwargs = field(init=False, repr=False, compare=False)

    new_cls = dataclass(cls, slots=True)
    dc_init = new_cls.__init__

    @wraps(dc_init)
    def new_init(self, *args, **kwargs):
        dc_init(self, *args, **kwargs)
        self._used_kwargs = kwargs

    new_cls.__init__ = new_init

    return new_cls

@debug_dataclass
class Example:
    answer: int = 42
    name: str = "Zaphod"
    mystery: Unknown = field(default=None, repr=False)

print(Example()._used_kwargs)  # {}
print(Example(54, name="Dent")._used_kwargs)  # {'name': 'Dent'}

# Define Unknown here and it will allow the annotations to evaluate
Unknown = None | str
print(get_annotations(Example))  # {'answer': <class 'int'>, 'name': <class 'str'>, 'mystery': None | str, '_used_kwargs': dict[str, object]}
```

### Checking which annotations can be evaluated ###

With the `FORWARDREF` format, it is not simple to know which annotations would fail to evaluate as
forward references can be contained in other arbitrary objects.

`DeferredAnnotation` instances have an `.is_resolved` property which indicates if the annotation
has been fully evaluated.

```python
from annotationlib import Format
from reannotate import get_deferred_annotations

def f(a: str, b: list[undefined]): ...

annos = get_deferred_annotations(f)

print(annos['a'].evaluate(format=Format.FORWARDREF))  # <class 'str'>
print(annos['a'].is_resolved)  # True
print(annos['b'].evaluate(format=Format.FORWARDREF))  # list[ForwardRef('undefined', ...)]
print(annos['b'].is_resolved)  # False
```

## What about... ##

### Metaclasses ###

`call_annotate_deferred` is provided to retrieve deferred annotations in the same way that
`call_annotate_function` is used to retrieve standard annotations.

### __future__ annotations ###

Deferred annotations are intended to act like regular annotations when called with the standard
annotation evaluation methods in order to create new `__annotate__` functions that behave like
the original.

If `__future__` annotations are used, `get_deferred_annotations` will still get `DeferredAnnotation`
objects, but all formats will evaluate to strings, as they do for `__future__` annotations with
`annotationlib.get_annotations`.

## Type Aliases ##

Like `get_annotations`, type aliases inside `DeferredAnnotation` objects will not be evaluated.

```python
from reannotate import get_deferred_annotations

type Vector = list[float]

def f(v: Vector): ...

v_anno = get_deferred_annotations(f)['v']
print(v_anno.evaluate())  # Vector
```
