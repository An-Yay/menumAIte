interface StarRatingProps {
  rating?: number | null;
  ratingCount?: number | null;
}

/** Renders a Google-style rating + count. Renders nothing misleading when
 * data is missing -- shows an explicit "no rating yet" instead of a blank. */
export function StarRating({ rating, ratingCount }: StarRatingProps) {
  if (rating == null) {
    return <span className="star-rating star-rating--empty">No rating yet</span>;
  }

  const full = Math.round(rating);
  return (
    <span className="star-rating">
      <span className="star-rating__stars" aria-hidden>
        {"★".repeat(full)}
        {"☆".repeat(5 - full)}
      </span>
      <span className="star-rating__value">{rating.toFixed(1)}</span>
      {ratingCount != null && (
        <span className="star-rating__count">({ratingCount.toLocaleString()})</span>
      )}
    </span>
  );
}
