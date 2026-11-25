import { CloudLightning, Droplets, Flame, Route, ThermometerSun, TrainFront, Waves, Zap, type LucideProps } from 'lucide-react';
import { HAZARD_LABELS, SECTOR_LABELS, isSector } from '../lib/model';

const SECTOR_ICONS = { roads: Route, rail: TrainFront, water: Droplets, energy: Zap };
const HAZARD_ICONS = { heatwave: ThermometerSun, flood: Waves, bushfire: Flame, storm: CloudLightning };

/** Sector icon. Sector is never shown by colour alone: pair with a label or aria-label. */
export function SectorIcon({ sector, size = 16, ...rest }: { sector: string } & LucideProps) {
  const Icon = isSector(sector) ? SECTOR_ICONS[sector] : Route;
  return <Icon size={size} aria-hidden="true" {...rest} />;
}

export function SectorBadge({ sector }: { sector: string }) {
  return (
    <span className={`sector-badge sector-${sector}`}>
      <SectorIcon sector={sector} size={13} />
      {isSector(sector) ? SECTOR_LABELS[sector] : sector}
    </span>
  );
}

export function HazardIcon({ type, size = 16, ...rest }: { type: string } & LucideProps) {
  const Icon = (HAZARD_ICONS as Record<string, typeof Flame>)[type] ?? CloudLightning;
  return <Icon size={size} aria-label={HAZARD_LABELS[type] ?? type} {...rest} />;
}
