"""Restock rules: config.txt `buyAuto` / `getAuto` blocks, edited in place (skillcfg).

Verified in OpenKore src:
  AI.pm (trigger) - buyAuto goes to town when the bag holds <= minAmount and
    < maxAmount (both must be set, and npc); getAuto likewise unless passive 1.
    A buyAuto value of 3+ digits is matched by item ID, anything else by name.
  AI/CoreLogic.pm (buying) - buys up to maxAmount; skipped when zeny < price
    or zeny is outside the `zeny` range (Utils inRange: "> 15000", ">= 1000").
Only the lines the user changed are rewritten; standpoint, distance and any
hand-written condition lines stay as they are.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from . import skillcfg as S
from .kconfig import KConfig

BUY: Final[str] = 'buyAuto'
GET: Final[str] = 'getAuto'
KIND_TH: Final[dict[str, str]] = {BUY: 'ซื้อจาก NPC', GET: 'เบิกจากคลัง'}
NPC_RE: Final[re.Pattern[str]] = re.compile(r'^[\w@.-]+ \d+ \d+$')
_ZENY_FLOOR_RE = re.compile(r'^\s*>=?\s*(\d+)\s*$')


def _int(raw: str | None) -> int | None:
    try:
        return int(str(raw).strip()) if raw is not None and str(raw).strip() != '' else None
    except ValueError:
        return None


def zeny_floor(raw: str | None) -> int | None:
    """'> 15000' / '>= 15000' -> 15000; None when absent or another form ('1000..5000')."""
    m = _ZENY_FLOOR_RE.match(raw or '')
    return int(m.group(1)) if m else None


@dataclass
class Rule:
    key: str                         # BUY / GET
    value: str                       # item name or ID, as written in config.txt
    ref: S.SkillRef | None = None    # None = not in config.txt yet
    npc: str = ''
    price: int | None = None
    min_amount: int | None = None
    max_amount: int | None = None
    zeny_min: int | None = None      # buy only while zeny > this
    zeny_raw: str = ''               # the zeny line as written (kept if not a plain floor)
    passive: bool = False
    enabled: bool = True
    extra: list[tuple[str, str]] = field(default_factory=list)   # other lines, shown read-only

    @property
    def item_id(self) -> int | None:
        v = self.value.strip()
        return int(v) if v.isdigit() else None


_KNOWN: Final[frozenset[str]] = frozenset({'npc', 'price', 'minAmount', 'maxAmount', 'zeny', 'passive', 'disabled'})


def load(kc: KConfig) -> list[Rule]:
    out: list[Rule] = []
    for key in (BUY, GET):
        for ref in S.all_refs(kc, key):
            r = Rule(key, ref.value, ref)
            r.npc = (ref.get('npc') or '').strip()
            r.price = _int(ref.get('price'))
            r.min_amount = _int(ref.get('minAmount'))
            r.max_amount = _int(ref.get('maxAmount'))
            r.zeny_raw = (ref.get('zeny') or '').strip()
            r.zeny_min = zeny_floor(r.zeny_raw)
            r.passive = (ref.get('passive') or '0').strip() not in ('', '0')
            r.enabled = ref.enabled
            r.extra = [(k, v) for k, v in ref.attrs if k not in _KNOWN and v.strip()]
            out.append(r)
    return out


def validate(r: Rule) -> None:
    """Raises ValueError with a Thai message the GUI can show."""
    if not r.value.strip():
        raise ValueError('ยังไม่ได้เลือกไอเทม')
    if r.min_amount is None or r.max_amount is None:
        raise ValueError('ต้องใส่จำนวนต่ำสุดและสูงสุด (OpenKore ไม่ทำงานถ้าไม่มีทั้งสองค่า)')
    if r.min_amount < 0 or r.max_amount <= 0 or r.min_amount >= r.max_amount:
        raise ValueError('จำนวนต่ำสุดต้องน้อยกว่าสูงสุด และสูงสุดต้องมากกว่า 0')
    if r.key == BUY:
        if not NPC_RE.match(r.npc.strip()):
            raise ValueError(f'ตำแหน่งร้าน "{r.npc}" ต้องเป็นรูปแบบ "แผนที่ x y" เช่น payon 159 96')
        for name, v in (('ราคา', r.price), ('เงินขั้นต่ำ', r.zeny_min)):
            if v is not None and v < 0:
                raise ValueError(f'{name} ต้องไม่ติดลบ')


def apply(kc: KConfig, r: Rule) -> None:
    """Write one rule into kc (create or edit in place). Raises ValueError / LookupError."""
    validate(r)
    changes: dict[str, str | None] = {
        'minAmount': str(r.min_amount), 'maxAmount': str(r.max_amount), 'disabled': '0' if r.enabled else '1'}
    if r.key == BUY:
        changes['npc'] = r.npc.strip()
        changes['price'] = str(r.price) if r.price else None
        if r.zeny_min is not None or not r.zeny_raw:      # leave an unusual zeny range alone
            changes['zeny'] = f'> {r.zeny_min}' if r.zeny_min else None
    else:
        changes['passive'] = '1' if r.passive else '0'
    if r.ref is None:
        attrs: dict[str, str] = {}
        if r.key == BUY:
            attrs['npc'] = r.npc.strip()
            attrs['distance'] = '5'
        attrs.update({k: v for k, v in changes.items() if v is not None and k != 'npc'})
        S.create(kc, r.key, r.value.strip(), attrs)
        refs = [x for x in S.all_refs(kc, r.key) if x.value == r.value.strip()]
        r.ref = refs[-1]
        return
    S.edit(kc, r.ref, changes)
    if r.value.strip() != r.ref.value:                    # item changed: rename the block, keep its body
        b = kc.find_block(r.ref.key, r.ref.value, r.ref.ordinal)
        if b is None:
            raise LookupError(f'block {r.ref.key} {r.ref.value} is gone (file changed?)')
        start = b.start
        kc.replace_block(b, r.value.strip(), kc.block_text(b))
        r.ref = _ref_at(kc, r.key, start)


def _ref_at(kc: KConfig, key: str, start: int) -> S.SkillRef | None:
    """The (value, ordinal) identity of the `key` block that starts at line `start`."""
    counts: dict[str, int] = {}
    for b in kc.blocks:
        if b.key != key:
            continue
        n = counts.get(b.value, 0)
        counts[b.value] = n + 1
        if b.start == start:
            return S.SkillRef(b.key, b.value, n, kc.block_items(b))
    return None


def remove(kc: KConfig, r: Rule) -> None:
    if r.ref is not None:
        S.delete(kc, r.ref)
        kc.trim_trailing_blank()
