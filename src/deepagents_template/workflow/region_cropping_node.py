"""Overview: Region-cropping node for writing region-local raster crops to disk."""

from __future__ import annotations

from PIL import Image

from deepagents_template.utils.image_runtime import crop_region_image


class RegionCroppingNodeMixin:
    """Implements the region-cropping workflow node."""

    def _run_region_cropping_node(
        self,
        *,
        image: Image.Image,
        regions: list[dict],
    ) -> list[dict]:
        self._push_event(
            "region-cropping",
            "Running region-cropping node",
            f"Cutting {len(regions)} model-planned non-overlapping regions from the source image.",
            payload={"regions_total": len(regions)},
        )
        region_work_items: list[dict] = []
        for region in regions:
            region_id = region["region_id"]
            region_dir = self.root_intermediate_dir / "regions" / region_id
            region_dir.mkdir(parents=True, exist_ok=True)
            crop_path = region_dir / "crop.png"
            crop_region_image(image, region["bbox"], crop_path)
            self._write_json(region_dir / "region_plan.json", region)
            region_work_items.append({"region": region, "region_dir": region_dir, "crop_path": crop_path})
        return region_work_items
