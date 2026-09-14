import { StarRating } from "./StarRating";
import { MenuItemRow } from "./MenuItemRow";
import type { Suggestion } from "../../types/models";

interface RestaurantCardProps {
  suggestion: Suggestion;
}

/** A single recommendation: restaurant info, rating, recommended dishes with
 * honest pricing, review summary, context-specific matches, and web links. */
export function RestaurantCard({ suggestion }: RestaurantCardProps) {
  const { restaurant, reasoning, recommended_items, review_insight, menu_url, caveats } =
    suggestion;

  return (
    <article className="restaurant-card">
      <header className="restaurant-card__header">
        <div>
          <h3 className="restaurant-card__name">{restaurant.name}</h3>
          {restaurant.primary_type && (
            <p className="restaurant-card__type">{restaurant.primary_type}</p>
          )}
        </div>
        <StarRating rating={restaurant.rating} ratingCount={restaurant.rating_count} />
      </header>

      {restaurant.address && <p className="restaurant-card__address">{restaurant.address}</p>}

      <p className="restaurant-card__reasoning">{reasoning}</p>

      {recommended_items.length > 0 && (
        <div className="restaurant-card__section">
          <h4>Recommended dishes</h4>
          <ul className="menu-item-list">
            {recommended_items.map((item, i) => (
              <MenuItemRow key={`${item.name}-${i}`} item={item} />
            ))}
          </ul>
        </div>
      )}

      {review_insight && (
        <div className="restaurant-card__section restaurant-card__reviews">
          <h4>What reviewers say</h4>
          <div className="review-columns">
            {review_insight.positive_points.length > 0 && (
              <div className="review-column review-column--positive">
                <h5>Positive</h5>
                <ul>
                  {review_insight.positive_points.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>
              </div>
            )}
            {review_insight.negative_points.length > 0 && (
              <div className="review-column review-column--negative">
                <h5>Negative</h5>
                <ul>
                  {review_insight.negative_points.map((point, i) => (
                    <li key={i}>{point}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          {review_insight.context_matches.length > 0 && (
            <div className="review-context">
              <h5>Relevant to your request</h5>
              <ul>
                {review_insight.context_matches.map((point, i) => (
                  <li key={i}>{point}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="review-context__count">
            Based on {review_insight.reviews_considered} reviews
          </p>
        </div>
      )}

      {caveats.length > 0 && (
        <ul className="restaurant-card__caveats">
          {caveats.map((caveat, i) => (
            <li key={i}>{caveat}</li>
          ))}
        </ul>
      )}

      <footer className="restaurant-card__links">
        {restaurant.website_url && (
          <a href={restaurant.website_url} target="_blank" rel="noreferrer">
            Website
          </a>
        )}
        {menu_url && (
          <a href={menu_url} target="_blank" rel="noreferrer">
            Menu
          </a>
        )}
        {restaurant.maps_url && (
          <a href={restaurant.maps_url} target="_blank" rel="noreferrer">
            Google Maps
          </a>
        )}
      </footer>
    </article>
  );
}
