interface ChipProps {
  label: string;
  selected?: boolean;
  onClick: () => void;
}

/** A single clickable quick-answer chip, used for meal and dietary picks. */
export function Chip({ label, selected = false, onClick }: ChipProps) {
  return (
    <button
      type="button"
      className={`chip${selected ? " chip--selected" : ""}`}
      aria-pressed={selected}
      onClick={onClick}
    >
      {label}
    </button>
  );
}
