from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass(slots=True)
class Anchor:
    href: str
    text: str = ""
    image_url: str | None = None
    image_alt: str | None = None
    rating_value: str | None = None
    rating_count: str | None = None


class RecipeHtmlParser(HTMLParser):
    """Small dependency-free parser for structured scripts and semantic fallback."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld: list[str] = []
        self.json_data: list[str] = []
        self.anchors: list[Anchor] = []
        self.meta: dict[str, str] = {}
        self.h1_parts: list[str] = []
        self.ingredient_parts: list[list[str]] = []
        self.instruction_parts: list[list[str]] = []
        self._script_parts: list[str] | None = None
        self._script_kind: str | None = None
        self._anchor: Anchor | None = None
        self._in_h1 = False
        self._ingredient_depth = 0
        self._instruction_depth = 0
        self._section_heading_parts: list[str] | None = None
        self._instruction_section = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        script_type = values.get("type", "").lower().split(";")[0].strip()
        if tag == "script" and script_type in {"application/ld+json", "application/json"}:
            self._script_parts = []
            self._script_kind = script_type
        elif tag == "a" and values.get("href"):
            self._anchor = Anchor(values["href"])
        elif tag == "img" and self._anchor is not None:
            # Publisher srcset URLs can contain literal commas in resize query
            # values (for example ``resize=372,338``). Treating every comma as
            # a candidate separator produced invalid paths such as ``/338``.
            # The ordinary image URL is lower resolution but consistently valid.
            self._anchor.image_url = (
                values.get("data-src")
                or values.get("data-lazy-src")
                or values.get("src")
                or self._anchor.image_url
                or None
            )
            self._anchor.image_alt = values.get("alt") or self._anchor.image_alt or None
        elif tag == "meta":
            key = values.get("property") or values.get("name") or values.get("itemprop")
            content = values.get("content")
            if key and content:
                self.meta[key.lower()] = content.strip()
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "h2":
            # A new top-level section closes the preceding Directions section.
            # Whether this heading opens another one is known at its end tag.
            self._section_heading_parts = []
            self._instruction_section = False

        if self._anchor is not None:
            itemprop = {part.strip().lower() for part in values.get("itemprop", "").split()}
            if "ratingvalue" in itemprop:
                self._anchor.rating_value = values.get("content") or values.get("value") or self._anchor.rating_value
            if itemprop & {"ratingcount", "reviewcount"}:
                self._anchor.rating_count = values.get("content") or values.get("value") or self._anchor.rating_count
            self._anchor.rating_value = (
                values.get("data-rating-value")
                or values.get("data-star-rating")
                or self._anchor.rating_value
            )
            label = values.get("aria-label") or values.get("title") or ""
            label_rating = re.search(
                r"(?:rated?|rating(?:\s+of)?)\s*([0-5](?:\.\d+)?)\s*(?:out of 5)?",
                label,
                flags=re.IGNORECASE,
            )
            if label_rating:
                self._anchor.rating_value = self._anchor.rating_value or label_rating.group(1)
            label_count = re.search(
                r"(\d[\d,]*)\s+(?:ratings?|reviews?)",
                label,
                flags=re.IGNORECASE,
            )
            if label_count:
                self._anchor.rating_count = self._anchor.rating_count or label_count.group(1)

        itemprop = {part.strip().lower() for part in values.get("itemprop", "").split()}
        if "recipeingredient" in itemprop or "ingredients" in itemprop:
            self._ingredient_depth += 1
            self.ingredient_parts.append([])
        elif self._ingredient_depth:
            self._ingredient_depth += 1

        if self._instruction_section:
            if tag == "li" and not self._instruction_depth:
                self._instruction_depth = 1
                self.instruction_parts.append([])
            elif self._instruction_depth:
                self._instruction_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._script_parts is not None:
            target = self.json_ld if self._script_kind == "application/ld+json" else self.json_data
            target.append("".join(self._script_parts))
            self._script_parts = None
            self._script_kind = None
        elif tag == "a" and self._anchor is not None:
            self._anchor.text = " ".join(self._anchor.text.split())
            self.anchors.append(self._anchor)
            self._anchor = None
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "h2" and self._section_heading_parts is not None:
            heading = " ".join(" ".join(self._section_heading_parts).split()).casefold()
            self._instruction_section = bool(
                re.match(r"^(?:directions?|instructions?|method|steps?)(?:\b|\s*:)", heading)
            )
            self._section_heading_parts = None
        if self._ingredient_depth:
            self._ingredient_depth -= 1
        if self._instruction_depth:
            self._instruction_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._script_parts is not None:
            self._script_parts.append(data)
        if self._anchor is not None:
            self._anchor.text += f" {data}"
        if self._in_h1:
            self.h1_parts.append(data)
        if self._section_heading_parts is not None:
            self._section_heading_parts.append(data)
        if self._ingredient_depth and self.ingredient_parts:
            self.ingredient_parts[-1].append(data)
        if self._instruction_depth and self.instruction_parts:
            self.instruction_parts[-1].append(data)

    @property
    def h1(self) -> str | None:
        value = " ".join(" ".join(self.h1_parts).split())
        return value or None

    @property
    def ingredients(self) -> tuple[str, ...]:
        values = (" ".join(" ".join(parts).split()) for parts in self.ingredient_parts)
        return tuple(dict.fromkeys(value for value in values if value))

    @property
    def instructions(self) -> tuple[str, ...]:
        values: list[str] = []
        for parts in self.instruction_parts:
            value = " ".join(" ".join(parts).split())
            value = re.sub(r"^step\s+\d+\s*[:.)-]?\s*", "", value, flags=re.IGNORECASE)
            if value and value not in values:
                values.append(value)
        return tuple(values)
