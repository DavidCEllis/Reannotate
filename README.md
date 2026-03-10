# Reannotate #

This library acts as an extension to the new deferred annotations that arrived as part of PEP-649/749
in Python 3.14.

The main goal of this library is to help handling cases where you need to retrieve the annotations at one point
but evaluate them later. One main use case being for creating new `__annotate__` callables.

Unlike `Format.FORWARDREF`, `get_deferred_annotations` will always return `DeferredAnnotation` objects as the values
of the annotations dictionary.

## Retrieving annotations ##

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

If a value is defined at a later point, the annotation can be evaluated fully.

```python
unknown = float

print(annos['b'].evaluate())
```

```python
list[float]
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

This can be useful for example if you wish to add fields to a dataclass. As dataclasses require fields
exist in the annotations, this is more difficult to do cleanly in Python 3.14+.

```python
from dataclasses import dataclass, field
from functools import wraps
from reannotate import get_deferred_annotations, ReAnnotate

def debug_dataclass(cls):
    annos = get_deferred_annotations(cls)

    annos |= {"_used_kwargs": dict[str, object]}

    cls.__annotate__ = ReAnnotate(annos)

    setattr(cls, "_used_kwargs", field(init=False, repr=False, compare=False))

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
    a: int = 42
    b: str = "Zaphod"

print(Example.__annotations__)  # {'a': <class 'int'>, 'b': <class 'str'>, '_used_kwargs': dict[str, object]}
print(Example()._used_kwargs)  # {}
print(Example(54, b="Dent")._used_kwargs)  # {'b': 'Dent'}
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
