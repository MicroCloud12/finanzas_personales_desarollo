"""
Campos cifrados transparentes para Django ORM y QuerySet compatible con índices ciegos.

En Python los atributos siguen siendo `str`, `Decimal` y `dict`/`list`, mientras que en
MySQL/SQLite se almacenan como `TEXT` con formato `enc:v1:<uid>:<token>`.
"""
import json
from decimal import Decimal, InvalidOperation

from django import forms
from django.core import validators
from django.db import models
from django.db.models import Q
from django.db.models.query import ModelIterable

from .crypto import blind_index, decrypt_str, encrypt_str, global_blind_index, is_encrypted


class _BoundValue:
    """Transporta (user_id, valor_limpio) desde pre_save hasta get_db_prep_save sin mutar la instancia."""
    __slots__ = ("user_id", "value")

    def __init__(self, user_id: int | None, value):
        self.user_id = user_id
        self.value = value


def resolve_owner_id(instance) -> int | None:
    if instance is None:
        return None
    uid = getattr(instance, "propietario_id", None) or getattr(instance, "usuario_id", None)
    if uid:
        return int(uid)

    cache = getattr(getattr(instance, "_state", None), "fields_cache", {}) or {}
    if "cuenta" in cache and cache["cuenta"] is not None and cache["cuenta"].propietario_id:
        return int(cache["cuenta"].propietario_id)
    if "deuda" in cache and cache["deuda"] is not None and cache["deuda"].propietario_id:
        return int(cache["deuda"].propietario_id)
    if "presupuesto" in cache and cache["presupuesto"] is not None and cache["presupuesto"].propietario_id:
        return int(cache["presupuesto"].propietario_id)

    cuenta_id = getattr(instance, "cuenta_id", None)
    if cuenta_id:
        from django.apps import apps
        Cuenta = apps.get_model("finanzas", "Cuenta")
        owner = Cuenta.objects.filter(pk=cuenta_id).values_list("propietario_id", flat=True).first()
        if owner:
            return int(owner)

    deuda_id = getattr(instance, "deuda_id", None)
    if deuda_id:
        from django.apps import apps
        Deuda = apps.get_model("finanzas", "Deuda")
        owner = Deuda.objects.filter(pk=deuda_id).values_list("propietario_id", flat=True).first()
        if owner:
            return int(owner)

    return None


class EncryptedFieldMixin:
    """Comportamiento común de serialización/cifrado por usuario."""

    def get_internal_type(self):
        return "TextField"

    def db_parameters(self, connection):
        # TextField ignora max_length/decimal_places en DDL de MySQL y SQLite
        return models.TextField().db_parameters(connection)

    def _serialize_plain(self, value) -> str:
        return str(value)

    def _deserialize_plain(self, text: str):
        return text

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        plain = decrypt_str(value) if is_encrypted(value) else value
        return self._deserialize_plain(plain)

    def pre_save(self, model_instance, add):
        raw = getattr(model_instance, self.attname)
        clean = self.to_python(raw)
        setattr(model_instance, self.attname, clean)
        return _BoundValue(resolve_owner_id(model_instance), clean)

    def get_db_prep_save(self, value, connection):
        if isinstance(value, _BoundValue):
            uid, raw = value.user_id, value.value
        else:
            uid, raw = None, self.to_python(value)

        if raw is None:
            return None
        if is_encrypted(raw):
            return raw
        serialized = self._serialize_plain(raw)
        return encrypt_str(serialized, uid)


class EncryptedCharField(EncryptedFieldMixin, models.Field):
    description = "Texto cifrado autenticado por usuario"

    def __init__(self, *args, max_length=255, **kwargs):
        kwargs["max_length"] = max_length
        super().__init__(*args, **kwargs)
        if self.max_length is not None:
            self.validators.append(validators.MaxLengthValidator(self.max_length))

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["max_length"] = self.max_length
        return name, path, args, kwargs

    def to_python(self, value):
        if value is None or isinstance(value, _BoundValue):
            return value
        if is_encrypted(value):
            return decrypt_str(value)
        return str(value)

    def _serialize_plain(self, value) -> str:
        return str(value)

    def _deserialize_plain(self, text: str) -> str:
        return "" if text is None else str(text)

    def formfield(self, **kwargs):
        defaults = {"max_length": self.max_length}
        if self.choices is not None:
            return super().formfield(**kwargs)
        defaults.update(kwargs)
        return super().formfield(form_class=forms.CharField, **defaults)


class EncryptedDecimalField(EncryptedFieldMixin, models.Field):
    description = "Decimal cifrado autenticado por usuario"
    empty_strings_allowed = False

    def __init__(self, *args, max_digits=20, decimal_places=2, **kwargs):
        self.max_digits = max_digits
        self.decimal_places = decimal_places
        self._quantizer = Decimal(10) ** -decimal_places if decimal_places is not None else None
        super().__init__(*args, **kwargs)
        self.validators.append(validators.DecimalValidator(max_digits, decimal_places))

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["max_digits"] = self.max_digits
        kwargs["decimal_places"] = self.decimal_places
        return name, path, args, kwargs

    def _quantize(self, dec: Decimal) -> Decimal:
        if self._quantizer is not None:
            return dec.quantize(self._quantizer)
        return dec

    def to_python(self, value):
        if value is None or isinstance(value, _BoundValue):
            return value
        if isinstance(value, Decimal):
            return value
        if is_encrypted(value):
            value = decrypt_str(value)
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise models.exceptions.ValidationError(f"Valor decimal inválido: {value!r}") from exc

    def _serialize_plain(self, value) -> str:
        dec = self.to_python(value)
        return format(self._quantize(dec), "f")

    def _deserialize_plain(self, text) -> Decimal | None:
        if text is None or text == "":
            return None
        if isinstance(text, Decimal):
            return self._quantize(text)
        return self._quantize(Decimal(str(text).strip()))

    def formfield(self, **kwargs):
        defaults = {
            "max_digits": self.max_digits,
            "decimal_places": self.decimal_places,
            "form_class": forms.DecimalField,
        }
        defaults.update(kwargs)
        return super().formfield(**defaults)


class EncryptedJSONField(EncryptedFieldMixin, models.Field):
    description = "JSON cifrado autenticado por usuario"
    empty_strings_allowed = False

    def to_python(self, value):
        if value is None or isinstance(value, _BoundValue):
            return value
        if isinstance(value, (dict, list, int, float, bool)):
            return value
        if is_encrypted(value):
            value = decrypt_str(value)
        if isinstance(value, str):
            texto = value.strip()
            if not texto:
                return {}
            try:
                return json.loads(texto)
            except json.JSONDecodeError:
                return value
        return value

    def _serialize_plain(self, value) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _deserialize_plain(self, text):
        if text is None:
            return None
        if isinstance(text, (dict, list)):
            return text
        return json.loads(text)

    def formfield(self, **kwargs):
        defaults = {"form_class": forms.JSONField}
        defaults.update(kwargs)
        return super().formfield(**defaults)


# ==============================================================================
# QuerySet compatible con Índices Ciegos (*_hash) y predicados sobre campos cifrados
# ==============================================================================

def _extract_owner_id_from_kwargs(kwargs: dict, fallback: int | None = None) -> int | None:
    for key in ("propietario", "propietario_id", "usuario", "usuario_id"):
        if key in kwargs and kwargs[key] is not None:
            val = kwargs[key]
            return int(val.pk if hasattr(val, "pk") else val)
    return fallback


def _match_lookup(actual, lookup: str, expected) -> bool:
    if lookup == "isnull":
        return (actual is None) is bool(expected)
    if actual is None:
        return expected is None and lookup in ("exact", "iexact")
    if lookup == "exact":
        if isinstance(actual, Decimal) and not isinstance(expected, Decimal):
            try:
                expected = Decimal(str(expected))
            except InvalidOperation:
                return False
        return actual == expected
    if lookup == "iexact":
        return str(actual).lower() == str(expected or "").lower()
    if lookup == "contains":
        return str(expected) in str(actual)
    if lookup == "icontains":
        return str(expected).lower() in str(actual).lower()
    if lookup == "startswith":
        return str(actual).startswith(str(expected))
    if lookup == "istartswith":
        return str(actual).lower().startswith(str(expected).lower())
    if lookup == "endswith":
        return str(actual).endswith(str(expected))
    if lookup == "iendswith":
        return str(actual).lower().endswith(str(expected).lower())
    if lookup == "in":
        if isinstance(actual, Decimal):
            norm = {Decimal(str(x)) if not isinstance(x, Decimal) else x for x in expected}
            return actual in norm
        return actual in expected
    if lookup == "gt":
        return actual > expected
    if lookup == "gte":
        return actual >= expected
    if lookup == "lt":
        return actual < expected
    if lookup == "lte":
        return actual <= expected
    raise TypeError(f"Lookup no soportado sobre campo cifrado: {lookup!r}")


class EncryptedQuerySet(models.QuerySet):
    """
    1. Si el modelo define `BLIND_INDEX_FIELDS = {'campo': ('campo_hash', 'user'|'global')}`,
       traduce automáticamente `campo=...` / `campo__iexact=...` al índice `campo_hash` en SQL.
    2. Si un filtro (`filter`/`exclude`/`get`/objetos `Q`) toca cualquier otro campo cifrado,
       ejecuta primero los filtros SQL normales (ej. `propietario`, `fecha`, `tipo`) y evalúa
       la condición cifrada en memoria devolviendo un QuerySet `pk__in=...`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._known_owner_id: int | None = None
        self._encrypted_order_by: tuple[str, ...] = ()

    def _clone(self):
        c = super()._clone()
        c._known_owner_id = self._known_owner_id
        c._encrypted_order_by = self._encrypted_order_by
        return c

    def order_by(self, *field_names):
        enc_names = self._encrypted_field_names()
        touches_enc = any(
            isinstance(f, str) and f.lstrip("-") in enc_names
            for f in field_names
        )
        if not touches_enc:
            c = super().order_by(*field_names)
            c._encrypted_order_by = ()
            return c
        sql_fields = [
            f for f in field_names
            if not (isinstance(f, str) and f.lstrip("-") in enc_names)
        ] or ["pk"]
        c = super().order_by(*sql_fields)
        c._encrypted_order_by = tuple(f for f in field_names if isinstance(f, str))
        return c

    def _sort_result_cache_in_place(self):
        if not self._encrypted_order_by or not self._result_cache:
            return
        if self._iterable_class is not ModelIterable:
            return
        # Python sort es estable: aplicamos de derecha a izquierda para respetar ascendente/descendente mixto
        for spec in reversed(self._encrypted_order_by):
            desc = spec.startswith("-")
            attr = spec.lstrip("-")

            def _key(obj, _attr=attr):
                val = getattr(obj, _attr, None)
                if isinstance(val, str):
                    return (val is None, val.lower())
                if isinstance(val, bool):
                    return (False, int(val))
                return (val is None, val if val is not None else 0)

            self._result_cache.sort(key=_key, reverse=desc)

    def _fetch_all(self):
        had_cache = self._result_cache is not None
        super()._fetch_all()
        if not had_cache and self._encrypted_order_by:
            self._sort_result_cache_in_place()

    def first(self):
        if self._encrypted_order_by:
            items = list(self)
            return items[0] if items else None
        return super().first()

    def last(self):
        if self._encrypted_order_by:
            items = list(self)
            return items[-1] if items else None
        return super().last()

    def _encrypted_field_names(self) -> set[str]:
        return {
            f.name for f in self.model._meta.get_fields()
            if isinstance(f, EncryptedFieldMixin)
        }

    def _blind_map(self) -> dict:
        return getattr(self.model, "BLIND_INDEX_FIELDS", {}) or {}

    def _q_touches_encrypted(self, q_obj: Q, enc_names: set[str]) -> bool:
        for child in q_obj.children:
            if isinstance(child, Q):
                if self._q_touches_encrypted(child, enc_names):
                    return True
            elif isinstance(child, tuple) and len(child) == 2:
                field_part = child[0].split("__", 1)[0]
                if field_part in enc_names:
                    return True
        return False

    def _eval_q_on_instance(self, obj, q_obj: Q) -> bool:
        results = []
        for child in q_obj.children:
            if isinstance(child, Q):
                res = self._eval_q_on_instance(obj, child)
            else:
                key, expected = child
                parts = key.split("__")
                # Soporta 1 nivel de relación o campo directo + lookup
                if len(parts) == 1:
                    field_name, lookup = parts[0], "exact"
                    actual = getattr(obj, field_name)
                elif len(parts) == 2 and parts[1] in (
                    "exact", "iexact", "contains", "icontains", "startswith",
                    "istartswith", "endswith", "iendswith", "in", "isnull",
                    "gt", "gte", "lt", "lte",
                ):
                    field_name, lookup = parts[0], parts[1]
                    actual = getattr(obj, field_name)
                else:
                    # Relación foránea + campo (ej. destino__tipo='AHORRO')
                    rel_obj = getattr(obj, parts[0], None)
                    if len(parts) == 2:
                        actual = getattr(rel_obj, parts[1], None) if rel_obj is not None else None
                        lookup = "exact"
                    else:
                        actual = getattr(rel_obj, parts[1], None) if rel_obj is not None else None
                        lookup = parts[2]
                res = _match_lookup(actual, lookup, expected)
            results.append(res)

        if q_obj.connector == Q.OR:
            matched = any(results) if results else True
        else:
            matched = all(results) if results else True
        return (not matched) if q_obj.negated else matched

    def _rewrite_blind_kwargs(self, kwargs: dict, owner_id: int | None) -> dict:
        blind_map = self._blind_map()
        if not blind_map:
            return dict(kwargs)
        out = {}
        for k, v in kwargs.items():
            parts = k.split("__")
            base = parts[0]
            lookup = parts[1] if len(parts) == 2 else ("exact" if len(parts) == 1 else None)
            if base in blind_map and lookup in ("exact", "iexact"):
                hash_field, mode = blind_map[base]
                if mode == "global":
                    out[hash_field] = "" if v is None else global_blind_index(v)
                    continue
                if mode == "user" and owner_id is not None:
                    out[hash_field] = blind_index(owner_id, "" if v is None else str(v))
                    continue
            out[k] = v
        return out

    def _filter_or_exclude(self, negate, args, kwargs):
        enc_names = self._encrypted_field_names()
        if not enc_names:
            return super()._filter_or_exclude(negate, args, kwargs)

        owner_id = _extract_owner_id_from_kwargs(kwargs, self._known_owner_id)
        rewritten = self._rewrite_blind_kwargs(kwargs, owner_id)

        sql_args, py_q_list = [], []
        for arg in args:
            if isinstance(arg, Q) and self._q_touches_encrypted(arg, enc_names):
                py_q_list.append(arg)
            else:
                sql_args.append(arg)

        sql_kwargs, py_kwargs = {}, {}
        for k, v in rewritten.items():
            base = k.split("__", 1)[0]
            if base in enc_names:
                py_kwargs[k] = v
            else:
                sql_kwargs[k] = v

        if not py_q_list and not py_kwargs:
            qs = super()._filter_or_exclude(negate, tuple(sql_args), sql_kwargs)
            if owner_id is not None and not negate:
                qs._known_owner_id = owner_id
            return qs

        # Si es filter normal, estrechamos primero en SQL con sql_args/sql_kwargs.
        # Si es exclude(), solo podemos estrechar aparte cuando no hay mezcla con sql_kwargs,
        # porque exclude(a=1, b=2) en Django significa NOT (a=1 AND b=2).
        combined_q = Q(*py_q_list, **py_kwargs)
        if not negate:
            base_qs = super()._filter_or_exclude(False, tuple(sql_args), sql_kwargs)
            if owner_id is not None:
                base_qs._known_owner_id = owner_id
            pks = [obj.pk for obj in base_qs if self._eval_q_on_instance(obj, combined_q)]
            res = self.model._base_manager.using(self.db).filter(pk__in=pks)
            if self.query.order_by:
                res = res.order_by(*self.query.order_by)
            res._encrypted_order_by = self._encrypted_order_by
            res._known_owner_id = owner_id
            return res

        # Caso negate=True (exclude): evaluamos el Q completo sobre el queryset actual
        full_q = Q(*args, **kwargs)
        pks_to_exclude = [obj.pk for obj in self if self._eval_q_on_instance(obj, full_q)]
        res = super()._filter_or_exclude(True, (), {"pk__in": pks_to_exclude})
        res._encrypted_order_by = self._encrypted_order_by
        res._known_owner_id = self._known_owner_id
        return res

    def get_or_create(self, defaults=None, **kwargs):
        enc_names = self._encrypted_field_names()
        blind_map = self._blind_map()
        if not (enc_names & set(kwargs)) and not (set(blind_map) & set(kwargs)):
            return super().get_or_create(defaults=defaults, **kwargs)

        try:
            return self.get(**kwargs), False
        except self.model.DoesNotExist:
            params = {k: v for k, v in kwargs.items() if "__" not in k}
            if defaults:
                params.update({
                    k: (v() if callable(v) else v) for k, v in defaults.items()
                })
            obj = self.model(**params)
            obj.save(force_insert=True, using=self.db)
            return obj, True

    def update_or_create(self, defaults=None, create_defaults=None, **kwargs):
        enc_names = self._encrypted_field_names()
        blind_map = self._blind_map()
        if not (enc_names & set(kwargs)) and not (set(blind_map) & set(kwargs)):
            return super().update_or_create(defaults=defaults, create_defaults=create_defaults, **kwargs)

        defaults = defaults or {}
        try:
            obj = self.get(**kwargs)
            for k, v in defaults.items():
                setattr(obj, k, v() if callable(v) else v)
            obj.save(using=self.db)
            return obj, False
        except self.model.DoesNotExist:
            params = {k: v for k, v in kwargs.items() if "__" not in k}
            extra = create_defaults if create_defaults is not None else defaults
            params.update({k: (v() if callable(v) else v) for k, v in extra.items()})
            obj = self.model(**params)
            obj.save(force_insert=True, using=self.db)
            return obj, True

    def update(self, **kwargs):
        enc_names = self._encrypted_field_names()
        blind_map = self._blind_map()
        if not (enc_names & set(kwargs)) and not (set(blind_map) & set(kwargs)):
            return super().update(**kwargs)

        objetos = list(self)
        for obj in objetos:
            for k, v in kwargs.items():
                setattr(obj, k, v)
            obj.save(using=self.db)
        return len(objetos)
