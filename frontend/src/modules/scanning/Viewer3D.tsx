import { GizmoHelper, GizmoViewport, Line, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useMemo } from "react";
import * as THREE from "three";
import { STATUS_COLOR, diverging, NO_DATA, sequential } from "./colors";
import type { CloudData, Hole, Mesh } from "./types";

export type ColorMode = "deviation" | "elevation" | "intensity";
export type DisplayMode = "points" | "mesh" | "both";

export interface ReferenceLayer {
  kind: "design" | "cloud";
  cloud?: CloudData;
}

interface Props {
  cloud: CloudData;
  mesh?: Mesh;
  holes?: Hole[];
  colorMode: ColorMode;
  display: DisplayMode;
  tolerance: number;
  sectionX: number | null;
  reference?: ReferenceLayer | null;
  pointSize: number;
}

const DESIGN_ANGLE = (75 * Math.PI) / 180;

/** Local face coordinates (x strike, y outward, z up) → three.js (proper rotation, y-up). */
function makeFrame(cloud: CloudData) {
  let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity, minz = Infinity, maxz = -Infinity;
  const p = cloud.xyz;
  for (let i = 0; i < cloud.n; i++) {
    const x = p[3 * i], y = p[3 * i + 1], z = p[3 * i + 2];
    if (x < minx) minx = x; if (x > maxx) maxx = x;
    if (y < miny) miny = y; if (y > maxy) maxy = y;
    if (z < minz) minz = z; if (z > maxz) maxz = z;
  }
  const c = [(minx + maxx) / 2, (miny + maxy) / 2, (minz + maxz) / 2];
  const map = (x: number, y: number, z: number): [number, number, number] => [x - c[0], z - c[2], -(y - c[1])];
  return { map, bbox: { minx, maxx, miny, maxy, minz, maxz }, size: Math.max(maxx - minx, maxy - miny, maxz - minz) };
}

function colorFor(mode: ColorMode, cloud: CloudData, i: number, tol: number, zmin: number, zmax: number): [number, number, number] {
  if (mode === "deviation") {
    const d = cloud.dev[i];
    return Number.isFinite(d) ? diverging(Math.max(-1, Math.min(1, d / (2 * tol)))) : NO_DATA;
  }
  if (mode === "elevation") return sequential((cloud.xyz[3 * i + 2] - zmin) / (zmax - zmin || 1));
  const v = 0.15 + 0.85 * cloud.intensity[i];
  return [v, v, v];
}

function PointsLayer({ cloud, frame, colorMode, tol, size, mono }: { cloud: CloudData; frame: ReturnType<typeof makeFrame>; colorMode: ColorMode; tol: number; size: number; mono?: string }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array(cloud.n * 3);
    for (let i = 0; i < cloud.n; i++) {
      const [a, b, c] = frame.map(cloud.xyz[3 * i], cloud.xyz[3 * i + 1], cloud.xyz[3 * i + 2]);
      pos[3 * i] = a; pos[3 * i + 1] = b; pos[3 * i + 2] = c;
    }
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    return g;
  }, [cloud, frame]);
  useMemo(() => {
    if (mono) return;
    const col = new Float32Array(cloud.n * 3);
    const { minz, maxz } = frame.bbox;
    for (let i = 0; i < cloud.n; i++) {
      const [r, g, b] = colorFor(colorMode, cloud, i, tol, minz, maxz);
      col[3 * i] = r; col[3 * i + 1] = g; col[3 * i + 2] = b;
    }
    geom.setAttribute("color", new THREE.BufferAttribute(col, 3));
  }, [geom, cloud, colorMode, tol, frame, mono]);
  return (
    <points geometry={geom}>
      {mono ? <pointsMaterial size={size} color={mono} sizeAttenuation transparent opacity={0.35} /> : <pointsMaterial size={size} vertexColors sizeAttenuation />}
    </points>
  );
}

function MeshLayer({ mesh, frame, colorMode, tol }: { mesh: Mesh; frame: ReturnType<typeof makeFrame>; colorMode: ColorMode; tol: number }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const n = mesh.vertices.length / 3;
    const pos = new Float32Array(n * 3);
    const col = new Float32Array(n * 3);
    const { minz, maxz } = frame.bbox;
    for (let i = 0; i < n; i++) {
      const [a, b, c] = frame.map(mesh.vertices[3 * i], mesh.vertices[3 * i + 1], mesh.vertices[3 * i + 2]);
      pos[3 * i] = a; pos[3 * i + 1] = b; pos[3 * i + 2] = c;
      const d = mesh.deviation[i];
      const rgb = colorMode === "deviation"
        ? (d === null ? NO_DATA : diverging(Math.max(-1, Math.min(1, d / (2 * tol)))))
        : colorMode === "elevation" ? sequential((mesh.vertices[3 * i + 2] - minz) / (maxz - minz || 1)) : ([0.62, 0.64, 0.68] as [number, number, number]);
      col.set(rgb, 3 * i);
    }
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.setIndex(mesh.indices);
    g.computeVertexNormals();
    return g;
  }, [mesh, frame, colorMode, tol]);
  return (
    <mesh geometry={geom}>
      <meshStandardMaterial vertexColors side={THREE.DoubleSide} roughness={0.9} metalness={0} />
    </mesh>
  );
}

function DesignLayer({ frame }: { frame: ReturnType<typeof makeFrame> }) {
  const geom = useMemo(() => {
    const { minx, maxx, maxz } = frame.bbox;
    const H = Math.round(maxz - 0.05);
    const toeY = H / Math.tan(DESIGN_ANGLE);
    const P = (x: number, y: number, z: number) => frame.map(x, y, z);
    const quads = [
      [P(minx, 0, H), P(maxx, 0, H), P(maxx, toeY, 0), P(minx, toeY, 0)], // face
      [P(minx, -9, H), P(maxx, -9, H), P(maxx, 0, H), P(minx, 0, H)], // top
      [P(minx, toeY, 0), P(maxx, toeY, 0), P(maxx, toeY + 10, 0), P(minx, toeY + 10, 0)], // floor
    ];
    const pos: number[] = [];
    for (const q of quads) pos.push(...q[0], ...q[1], ...q[2], ...q[0], ...q[2], ...q[3]);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    return g;
  }, [frame]);
  return (
    <>
      <mesh geometry={geom}>
        <meshBasicMaterial color="#e8742c" transparent opacity={0.12} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      <lineSegments>
        <edgesGeometry args={[geom]} />
        <lineBasicMaterial color="#e8742c" transparent opacity={0.6} />
      </lineSegments>
    </>
  );
}

function SectionPlane({ x, frame }: { x: number; frame: ReturnType<typeof makeFrame> }) {
  const { miny, maxy, minz, maxz } = frame.bbox;
  const [a] = frame.map(x, 0, 0);
  const [, b, c] = frame.map(x, (miny + maxy) / 2, (minz + maxz) / 2);
  return (
    <mesh position={[a, b, c]} rotation={[0, Math.PI / 2, 0]}>
      <planeGeometry args={[maxy - miny + 2, maxz - minz + 2]} />
      <meshBasicMaterial color="#e8742c" transparent opacity={0.18} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  );
}

function HolesLayer({ holes, frame }: { holes: Hole[]; frame: ReturnType<typeof makeFrame> }) {
  return (
    <>
      {holes.map((h) => (
        <Line key={h.id} points={[frame.map(h.x, h.y, h.z + 0.4), frame.map(h.x, h.y, h.z - h.depth_m)]} color={STATUS_COLOR[h.status] ?? "#999"} lineWidth={2.5} />
      ))}
    </>
  );
}

export default function Viewer3D({ cloud, mesh, holes, colorMode, display, tolerance, sectionX, reference, pointSize }: Props) {
  const frame = useMemo(() => makeFrame(cloud), [cloud]);
  const d = frame.size;
  return (
    <Canvas camera={{ position: [d * 0.35, d * 0.35, -d * 0.85], fov: 45, near: 0.1, far: d * 20 }} dpr={[1, 2]} gl={{ antialias: true, preserveDrawingBuffer: true }}>
      <color attach="background" args={["#0a111d"]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[d, d * 1.5, -d]} intensity={1.1} />
      <directionalLight position={[-d, d, d]} intensity={0.35} />
      {(display === "points" || display === "both") && <PointsLayer cloud={cloud} frame={frame} colorMode={colorMode} tol={tolerance} size={pointSize} />}
      {(display === "mesh" || display === "both") && mesh && <MeshLayer mesh={mesh} frame={frame} colorMode={colorMode} tol={tolerance} />}
      {reference?.kind === "design" && <DesignLayer frame={frame} />}
      {reference?.kind === "cloud" && reference.cloud && <PointsLayer cloud={reference.cloud} frame={frame} colorMode="elevation" tol={tolerance} size={pointSize} mono="#e8742c" />}
      {holes && holes.length > 0 && <HolesLayer holes={holes} frame={frame} />}
      {sectionX !== null && <SectionPlane x={sectionX} frame={frame} />}
      <gridHelper args={[Math.ceil(d * 1.6), Math.ceil(d * 1.6) / 2, "#22304a", "#16213a"]} position={[0, frame.bbox.minz - (frame.bbox.minz + frame.bbox.maxz) / 2 - 0.05, 0]} />
      <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
      <GizmoHelper alignment="bottom-right" margin={[64, 64]}>
        <GizmoViewport axisColors={["#d95926", "#199e70", "#3987e5"]} labels={["x", "z", "-y"]} labelColor="#0b1220" />
      </GizmoHelper>
    </Canvas>
  );
}
