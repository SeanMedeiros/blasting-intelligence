"""Synthetic bench-face point clouds and geometric comparison.

SIMULATED DATA. Point clouds are generated deterministically from each survey's
id, so the same survey always produces the same cloud. The browser receives a
decimated sample (display_points); the survey record keeps the nominal point count
of the original scan.

Local face coordinate system (metres):
    x — along the face (strike)
    y — horizontal, positive towards the free space (crest of the design face at y = 0)
    z — elevation above the bench toe (bench floor at z = 0, crest at z = H)

Region codes per point: 0 face, 1 bench top, 2 floor, 3 muckpile, 255 unknown (imported).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree

DESIGN_FACE_ANGLE_DEG = 75.0  # demonstration value for the synthetic design face
BURDEN_LOCAL_M = 3.5  # front-row offset used to place the fictional pattern behind the crest
SPACING_LOCAL_M = 4.0
SCANNER_POS = np.array([0.0, 45.0, 6.0])  # nominal scanner position (x set to face centre at runtime)

REGION_FACE, REGION_TOP, REGION_FLOOR, REGION_MUCK, REGION_UNKNOWN = 0, 1, 2, 3, 255


@dataclass
class FaceSpec:
    seed: int
    length_m: float
    height_m: float
    survey_type: str  # FACE_PROFILE | POST_BLAST | PRE_BLAST
    rows: int = 4
    planted: bool = False  # strong toe bulge and crest overbreak
    display_points: int = 160_000


@dataclass
class Cloud:
    xyz: np.ndarray  # (N, 3) float64
    intensity: np.ndarray  # (N,) float32 in [0, 1]
    region: np.ndarray  # (N,) uint8
    spec: FaceSpec | None = None
    extras: dict = field(default_factory=dict)


# ------------------------------------------------------------------ synthetic surfaces
class _Field:
    """Smooth random field built from Gaussian bumps and low-amplitude waves."""

    def __init__(self, rng: np.random.Generator, length: float, height: float, amp: float, n: int):
        self.cx = rng.uniform(0, length, n)
        self.cz = rng.uniform(-1, height + 1, n)
        self.sx = rng.uniform(1.2, 4.5, n)
        self.sz = rng.uniform(0.8, 3.0, n)
        self.a = rng.normal(0, amp, n)
        self.k = rng.uniform(0.6, 2.2, 3)
        self.ph = rng.uniform(0, 2 * math.pi, 3)
        self.wa = amp * 0.25

    def __call__(self, x: np.ndarray, z: np.ndarray) -> np.ndarray:
        out = np.zeros_like(x, dtype=float)
        for i in range(len(self.a)):
            out += self.a[i] * np.exp(-((x - self.cx[i]) ** 2) / (2 * self.sx[i] ** 2) - ((z - self.cz[i]) ** 2) / (2 * self.sz[i] ** 2))
        for k, ph in zip(self.k, self.ph):
            out += self.wa * np.sin(k * x + ph) * np.cos(0.7 * k * z + ph)
        return out


def design_face_y(z: np.ndarray, height: float) -> np.ndarray:
    return (height - z) / math.tan(math.radians(DESIGN_FACE_ANGLE_DEG))


def _face_function(spec: FaceSpec, rng: np.random.Generator, offset_y: float = 0.0):
    L, H = spec.length_m, spec.height_m
    rough = _Field(rng, L, H, amp=0.22, n=28)
    angle_var = _Field(rng, L, H, amp=1.0, n=6)
    toe_amp = 1.6 if spec.planted else rng.uniform(0.15, 0.35)
    crest_amp = -1.25 if spec.planted else -rng.uniform(0.1, 0.3)
    toe_cx, crest_cx = rng.uniform(0.5, 0.75) * L, rng.uniform(0.2, 0.4) * L

    def f(x, z):
        ang = np.radians(DESIGN_FACE_ANGLE_DEG + 2.0 * angle_var(x, np.full_like(x, H / 2)))
        y = (H - z) / np.tan(ang)
        y += rough(x, z)
        y += toe_amp * np.exp(-((x - toe_cx) ** 2) / (2 * 5.0 ** 2)) * np.exp(-z / 1.0)
        y += crest_amp * np.exp(-((x - crest_cx) ** 2) / (2 * 4.0 ** 2)) * np.exp(-(H - z) / 0.9)
        return y + offset_y

    return f


def generate_cloud(spec: FaceSpec) -> Cloud:
    rng = np.random.default_rng(spec.seed)
    L, H, N = spec.length_m, spec.height_m, spec.display_points
    noise = 0.006  # 6 mm scanner range noise (simulated)

    if spec.survey_type == "POST_BLAST":
        removed = spec.rows * BURDEN_LOCAL_M
        face = _face_function(FaceSpec(spec.seed + 7, L, H, "FACE_PROFILE"), rng, offset_y=-removed)
        S = removed + 16.0
        Hm = 0.62 * H
        lumps = _Field(rng, L, S, amp=0.35, n=60)

        def muck(x, y):
            s = np.clip(y - face(x, np.zeros_like(x)), 0, None)
            h = Hm * np.clip(1 - (s / S) ** 2, 0, None) * (0.85 + 0.15 * np.cos(x / L * 2 * math.pi))
            return np.where(s < S, h + lumps(x, s) * (h > 0.2), 0.0)

        n_face, n_top, n_muck, n_floor = int(N * 0.32), int(N * 0.18), int(N * 0.4), N - int(N * 0.32) - int(N * 0.18) - int(N * 0.4)
        x = rng.uniform(0, L, n_face * 2)
        z = rng.uniform(0, H, n_face * 2)
        y = face(x, z)
        visible = z > muck(x, y + 0.05)
        x, y, z = x[visible][:n_face], y[visible][:n_face], z[visible][:n_face]
        face_pts = np.c_[x, y, z]
        xt = rng.uniform(0, L, n_top)
        yt = face(xt, np.full(n_top, H)) - rng.uniform(0, 9, n_top)
        top = np.c_[xt, yt, H + rng.normal(0, 0.03, n_top)]
        xm = rng.uniform(0, L, n_muck)
        ym = face(xm, np.zeros(n_muck)) + rng.uniform(0, S, n_muck)
        zm = muck(xm, ym)
        muck_pts = np.c_[xm, ym, zm]
        xf = rng.uniform(0, L, n_floor)
        yf = face(xf, np.zeros(n_floor)) + S + rng.uniform(0, 6, n_floor)
        floor = np.c_[xf, yf, rng.normal(0, 0.04, n_floor)]
        parts = [(face_pts, REGION_FACE), (top, REGION_TOP), (muck_pts, REGION_MUCK), (floor, REGION_FLOOR)]
    else:
        face = _face_function(spec, rng)
        n_face, n_top = int(N * 0.62), int(N * 0.2)
        n_floor = N - n_face - n_top
        x = rng.uniform(0, L, n_face)
        z = rng.uniform(0, H, n_face)
        face_pts = np.c_[x, face(x, z), z]
        xt = rng.uniform(0, L, n_top)
        yt = face(xt, np.full(n_top, H)) - rng.uniform(0, 9, n_top)
        top = np.c_[xt, yt, H + rng.normal(0, 0.03, n_top)]
        xf = rng.uniform(0, L, n_floor)
        yf = face(xf, np.zeros(n_floor)) + rng.uniform(0, 10, n_floor)
        floor = np.c_[xf, yf, rng.normal(0, 0.03, n_floor)]
        parts = [(face_pts, REGION_FACE), (top, REGION_TOP), (floor, REGION_FLOOR)]

    xyz = np.vstack([p for p, _ in parts])
    region = np.concatenate([np.full(len(p), r, dtype=np.uint8) for p, r in parts])
    xyz = xyz + rng.normal(0, noise, xyz.shape)
    # simulated reflectance: banded lithology + per-point scatter
    band = 0.5 + 0.25 * np.sin(xyz[:, 2] * 1.7 + xyz[:, 0] * 0.15) + 0.1 * np.sin(xyz[:, 0] * 0.9)
    inten = np.clip(band + rng.normal(0, 0.08, len(xyz)), 0, 1).astype(np.float32)
    inten[region == REGION_MUCK] *= 0.8
    return Cloud(xyz=xyz, intensity=inten, region=region, spec=spec)


def design_cloud(length: float, height: float, n: int = 120_000, seed: int = 1) -> Cloud:
    """Design (as-planned) surface: planar face at the design angle, flat top and floor."""
    rng = np.random.default_rng(seed)
    nf, nt = int(n * 0.6), int(n * 0.2)
    nfl = n - nf - nt
    x = rng.uniform(0, length, nf)
    z = rng.uniform(0, height, nf)
    face = np.c_[x, design_face_y(z, height), z]
    xt = rng.uniform(0, length, nt)
    top = np.c_[xt, -rng.uniform(0, 9, nt), np.full(nt, height)]
    xf = rng.uniform(0, length, nfl)
    floor = np.c_[xf, design_face_y(np.zeros(nfl), height) + rng.uniform(0, 10, nfl), np.zeros(nfl)]
    xyz = np.vstack([face, top, floor])
    region = np.concatenate([np.full(nf, REGION_FACE), np.full(nt, REGION_TOP), np.full(nfl, REGION_FLOOR)]).astype(np.uint8)
    return Cloud(xyz=xyz, intensity=np.full(len(xyz), 0.5, np.float32), region=region)


# ------------------------------------------------------------------ comparison
def estimate_normals(xyz: np.ndarray, ref: np.ndarray, tree: cKDTree, k: int = 10, viewpoint: np.ndarray | None = None) -> np.ndarray:
    """PCA normals at xyz from neighbours in ref (indexed by tree), oriented towards the viewpoint."""
    _, idx = tree.query(xyz, k=k)
    nb = ref[idx]  # (N, k, 3)
    nb = nb - nb.mean(axis=1, keepdims=True)
    cov = np.einsum("nki,nkj->nij", nb, nb)
    _, vecs = np.linalg.eigh(cov)
    n = vecs[:, :, 0]
    if viewpoint is not None:
        flip = np.einsum("ij,ij->i", n, viewpoint - xyz) < 0
        n[flip] *= -1
    return n


def signed_distance(compared: np.ndarray, reference: np.ndarray, viewpoint: np.ndarray) -> np.ndarray:
    """Cloud-to-cloud signed distance using point-to-plane on the nearest reference point.

    Positive = compared surface lies on the scanner side of the reference (material present
    beyond the reference, e.g. underbreak or muck); negative = behind it (overbreak / removed).
    """
    tree = cKDTree(reference)
    _, nn = tree.query(compared, k=1)
    sample = np.unique(nn)
    normals = np.zeros_like(reference)
    normals[sample] = estimate_normals(reference[sample], reference, tree, viewpoint=viewpoint)
    d = np.einsum("ij,ij->i", compared - reference[nn], normals[nn])
    return d


def deviation_to_design(cloud: Cloud, design: Cloud, viewpoint: np.ndarray, height: float) -> np.ndarray:
    """Face points: exact perpendicular distance to the design face plane. Other points: cloud-to-cloud."""
    d = signed_distance(cloud.xyz, design.xyz, viewpoint)
    f = cloud.region == REGION_FACE
    a = math.radians(DESIGN_FACE_ANGLE_DEG)
    d[f] = (cloud.xyz[f, 1] - design_face_y(cloud.xyz[f, 2], height)) * math.sin(a)
    return d


def deviation_stats(d: np.ndarray, tol: float | None) -> dict:
    d = d[np.isfinite(d)]
    if d.size == 0:
        return {"count": 0}
    edges = np.linspace(-1.5, 1.5, 31)
    clipped = np.clip(d, -1.5, 1.5 - 1e-9)
    hist, _ = np.histogram(clipped, bins=edges)
    return {
        "count": int(d.size),
        "mean_m": round(float(d.mean()), 3),
        "std_m": round(float(d.std()), 3),
        "p05_m": round(float(np.percentile(d, 5)), 3),
        "p95_m": round(float(np.percentile(d, 95)), 3),
        "max_abs_m": round(float(np.abs(d).max()), 3),
        "within_tolerance_pct": round(float(100 * np.mean(np.abs(d) <= tol)), 1) if tol else None,
        "above_tolerance_pct": round(float(100 * np.mean(d > tol)), 1) if tol else None,
        "below_tolerance_pct": round(float(100 * np.mean(d < -tol)), 1) if tol else None,
        "tolerance_m": tol,
        "histogram": {"edges": [round(float(e), 2) for e in edges], "counts": [int(c) for c in hist]},
    }


# ------------------------------------------------------------------ mesh, profiles, front-row distance
def face_mesh(cloud: Cloud, deviation: np.ndarray | None, cell: float = 0.4) -> dict:
    """2.5D mesh of the face region: grid over (x, z), vertex y = median of points in the cell."""
    m = cloud.region == REGION_FACE
    if not m.any():
        m = np.ones(len(cloud.xyz), bool)  # imported cloud: grid everything over (x, z)
    p = cloud.xyz[m]
    dv = deviation[m] if deviation is not None else None
    x0, z0 = p[:, 0].min(), p[:, 2].min()
    nx = int(np.ceil((p[:, 0].max() - x0) / cell)) + 1
    nz = int(np.ceil((p[:, 2].max() - z0) / cell)) + 1
    ix = ((p[:, 0] - x0) / cell).astype(int)
    iz = ((p[:, 2] - z0) / cell).astype(int)
    key = iz * nx + ix
    order = np.argsort(key)
    keys, starts = np.unique(key[order], return_index=True)
    ys = np.split(p[order, 1], starts[1:])
    yv = np.full(nx * nz, np.nan)
    yv[keys] = [np.median(v) for v in ys]
    dvv = np.full(nx * nz, np.nan)
    if dv is not None:
        ds = np.split(dv[order], starts[1:])
        dvv[keys] = [np.nanmedian(v) if np.isfinite(v).any() else np.nan for v in ds]
    verts, devs, index = [], [], {}
    for k in range(nx * nz):
        if np.isfinite(yv[k]):
            index[k] = len(verts)
            verts.append((x0 + (k % nx + 0.5) * cell, float(yv[k]), z0 + (k // nx + 0.5) * cell))
            devs.append(None if not np.isfinite(dvv[k]) else round(float(dvv[k]), 3))
    tris = []
    for j in range(nz - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i, (j + 1) * nx + i + 1
            if a in index and b in index and c in index:
                tris += [index[a], index[b], index[c]]
            if b in index and d in index and c in index:
                tris += [index[b], index[d], index[c]]
    return {"vertices": [round(v, 3) for t in verts for v in t], "indices": tris, "deviation": devs, "cell_m": cell}


def section(cloud: Cloud, x0: float, half_width: float = 0.2, max_points: int = 2500) -> list[list[float]]:
    m = np.abs(cloud.xyz[:, 0] - x0) <= half_width
    p = cloud.xyz[m][:, [1, 2]]
    if len(p) > max_points:
        p = p[np.linspace(0, len(p) - 1, max_points).astype(int)]
    p = p[np.argsort(p[:, 1])]
    return [[round(float(a), 3), round(float(b), 3)] for a, b in p]


def front_row_distances(cloud: Cloud, holes_x: list[float], hole_y: float, height: float, bin_m: float = 0.25) -> list[dict]:
    """Horizontal distance from each vertical front-row hole to the surveyed face, by elevation.

    Geometric measurement only. No loading or design recommendation is derived from it.
    """
    m = cloud.region == REGION_FACE
    p = cloud.xyz[m]
    out = []
    for hx in holes_x:
        s = p[np.abs(p[:, 0] - hx) <= 0.35]
        if len(s) < 20:
            out.append({"x": hx, "valid": False})
            continue
        zb = np.floor(s[:, 2] / bin_m).astype(int)
        prof = []
        for b in np.unique(zb):
            ys = s[zb == b, 1]
            if len(ys) >= 3:
                prof.append(((b + 0.5) * bin_m, float(np.median(ys)) - hole_y))
        prof = np.array(prof)
        imin = int(np.argmin(prof[:, 1]))
        crest = prof[prof[:, 0] >= height - 1.0][:, 1]
        toe = prof[prof[:, 0] <= 1.0][:, 1]
        out.append({
            "x": round(hx, 2), "valid": True,
            "min_distance_m": round(float(prof[imin, 1]), 2), "min_at_z_m": round(float(prof[imin, 0]), 2),
            "crest_distance_m": round(float(crest.mean()), 2) if crest.size else None,
            "toe_distance_m": round(float(toe.mean()), 2) if toe.size else None,
            "profile": [[round(float(z), 2), round(float(d), 2)] for z, d in prof],
        })
    return out


# ------------------------------------------------------------------ serialization
def pack_binary(cloud: Cloud, deviation: np.ndarray | None) -> bytes:
    """Layout: uint32 N | uint32 flags | float32 xyz[3N] | float32 intensity[N] | float32 dev[N] | uint8 region[N]."""
    n = len(cloud.xyz)
    flags = 1 if deviation is not None else 0
    dev = deviation.astype(np.float32) if deviation is not None else np.full(n, np.nan, np.float32)
    head = np.array([n, flags], dtype="<u4").tobytes()
    return head + cloud.xyz.astype("<f4").tobytes() + cloud.intensity.astype("<f4").tobytes() + dev.astype("<f4").tobytes() + cloud.region.astype(np.uint8).tobytes()
