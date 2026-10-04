# Listing cover image

The image is a **brief for the operator to run**, not an asset you produce.

## The framing rule that matters most

Zomato's uploader rejects tightly-cropped flat-lays with *"Image is too zoomed in. Please upload a
clear and properly framed image."* Anything with vessels cut by the frame border trips it.

This is worth stating loudly because the instinctive food-photography brief — fill the frame edge
to edge, crop dishes at the borders, food at 75% — is exactly what fails. Ask instead for:

- The whole spread inside the frame, clear margin of empty surface on all four sides
- Nothing touching or crossing the frame edge
- Food at roughly **60%** of the frame, not 75%
- Camera pulled back, wide, the complete table setting visible at once

Put the framing instruction at the *front* of the prompt, not buried after the dish list. Image
models weight early tokens more heavily, and they resist wide framing by default.

If it still comes back cropped, drop to five vessels. Fewer objects makes the model pull back on
its own, and five with room to breathe photographs better than six that crowd.

## Choosing the dishes

Six, picked by **visual role rather than price**. The frame needs contrast in colour, height and
texture — not her six most expensive items:

| Role | What it does |
|---|---|
| A stack of flatbread | Height, and usually the most-repeated thing she cooks |
| A second bread, folded | Texture against the stack |
| A dark gravy | The strongest colour on the menu — spinach, gongura |
| A warm gravy | Golden-red against the dark one |
| A rice dish | Mass, and it breaks up all the round shapes |
| A bright geometric snack | Visual surprise — dhokla diamonds, cut sweets |
| Small bowls in the gaps | Curd, pickle, chutney — dots of colour |

Every dish must be one she actually sells. Nothing invented for the picture, and nothing that would
have her delivering against a photograph she cannot match.

## Adapting the visual idiom

Match the vessels to the cuisine. Brass thali, hammered steel and a handloom cotton runner suit
North Indian and Rajasthani menus; banana leaf and steel katoris suit South Indian ones. Using the
wrong idiom misrepresents the kitchen, and a customer notices before a validator does.

## Prompt skeleton

```
A wide overhead photograph, camera at 90 degrees directly above, of a group of dishes arranged in
the centre of a large dark [surface], with clear empty margins on all four sides. Every plate and
bowl sits completely inside the frame — nothing touches or crosses the edge of the picture.

[six numbered dishes with vessel, contents and garnish]

[small bowls tucked into the gaps]

Lighting: soft diffused natural daylight from the upper left, gentle shadows to the lower right,
no harsh highlights, no studio flash.

Styling: an authentic Indian home kitchen, not restaurant plating. [vessel idiom]. [cloth].
A few loose [herb] leaves and a scattering of [whole spice] on the surface.

Composition: the food occupies about 60 percent of the frame, centred, framed by open surface
around it. Wide, airy, the complete table setting visible at once.

Aspect ratio 16:9, minimum 1200 x 500 pixels, photorealistic, fine detail, professional food
photography.

Do not include: any dish, plate, bowl or cloth cut off by the edge of the frame; close-up or macro
framing; any text, lettering, numbers, watermarks, logos or signage; people, hands, arms or faces;
forks, knives, spoons or cutlery of any kind; plastic containers, cling film, takeaway boxes or
packaging; restaurant tables, menu cards or price tags; collage, grid or split-screen layouts.
```

## Compliance checklist

Hand this to whoever uploads. Any single failure means regenerate.

- No people anywhere — no faces, hands or arms
- No stock or web-sourced imagery
- No logo, text overlay, price, phone number or social handle inside the image
- Not a collage — one continuous photograph
- JPEG or PNG only, under 5 MB
- At least 1200 × 500, 16:9
- Food fills roughly 60% of the frame, centred, nothing cropped at the edges
- No cutlery, plastic packaging or takeaway containers
- The dishes shown match what she actually delivers

Expect four or five generation attempts. The usual failures are invented cutlery, a hand entering
frame, and text appearing on the cloth.

## After generation

Run `scripts/prep_image.py` on the result. It crops to exact 16:9, resizes to 1600×900, flattens
any alpha channel, and strips every metadata block — EXIF, XMP, ICC, IPTC and C2PA AI-provenance
tags. A 10 MB generated PNG comes out around 450 KB, comfortably inside the 5 MB limit.
