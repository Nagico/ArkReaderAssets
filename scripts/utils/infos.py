def get_valid_str_value(data: dict, key: str) -> str | None:
    if key in data and data[key]:
        return data[key]
    return None


class HotUpdateInfo:
    id: int
    name: str
    hash: str | None
    md5: str | None
    total_size: int
    ab_size: int
    type: str
    parent: str | None
    need_update: bool = True

    def __str__(self):
        return f"{self.name} ({self.type})"

    def __repr__(self):
        return f"HotUpdateInfo(name={self.name}, type={self.type}, total_size={self.total_size}, ab_size={self.ab_size})"

    @staticmethod
    def from_dict(data: dict) -> "HotUpdateInfo":
        info = HotUpdateInfo()
        info.id = data["cid"]
        info.name = data["name"]
        info.hash = get_valid_str_value(data, "hash")
        info.md5 = get_valid_str_value(data, "md5")
        info.total_size = data["totalSize"]
        info.ab_size = data["abSize"]
        info.type = get_valid_str_value(data, "type")
        info.parent = get_valid_str_value(data, "pid")
        return info
