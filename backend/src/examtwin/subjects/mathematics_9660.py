from examtwin.subjects.contracts import DefaultCurriculumTextNormalizer


class Mathematics9660TextNormalizer(DefaultCurriculumTextNormalizer):
    """Repair reviewed 9660 table continuations after generic structure extraction."""

    key = "mathematics-9660-v1"

    def objective_title(self, topic_title: str, raw_title: str) -> str:
        title = raw_title.strip().strip(";")
        lowered = title.lower()
        if lowered.startswith("and "):
            title = title[4:].strip()
            lowered = title.lower()
        if topic_title.lower() == "integration":
            prefix = "simple cases of integration:"
            if lowered.startswith(prefix):
                title = f"Integration {title[len(prefix) :].strip()}"
            elif lowered.startswith("by "):
                title = f"Integration {title}"
            elif lowered.startswith("these methods as the reverse processes"):
                title = title.replace("These methods", "Integration methods", 1)
        elif (
            topic_title.lower() == "continuous random variables"
            and lowered.rstrip(".") == "differences from discrete random variables"
        ):
            title = "Differences between continuous and discrete random variables"
        elif (
            "newton's law" in topic_title.lower()
            and lowered.rstrip(".") == "application to situations, with variable acceleration"
        ):
            title = "Applications of Newton's laws to motion with variable acceleration"
        title = title[:1].upper() + title[1:]
        return title.rstrip(".") + "."
