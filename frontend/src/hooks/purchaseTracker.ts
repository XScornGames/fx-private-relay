import { useEffect } from "react";
import { clearCookie, getCookie } from "../functions/cookies";
import { getCookieId, getGaCategory, Plan } from "../functions/trackPurchase";
import { ProfileData } from "./api/profile";
import { useGaEvent } from "./gaEvent";

/**
 * Include this in pages that Subscription platform sends the user back to
 * to count how many people purchased which plan.
 */
export const usePurchaseTracker = (profileData?: ProfileData) => {
  const gaEvent = useGaEvent();
  useEffect(() => {
    // This cookie is set in `trackPurchaseStart()`
    const hasClickedPurchaseCookie = getCookie("clicked-purchase") === "true";
    if (hasClickedPurchaseCookie && profileData?.has_premium) {
      gaEvent({
        // This used to be an event set by the server;
        // I kept that name even though it's now generated by the client
        // to ensure reports remain consistent:
        category: "server event",
        action: "fired",
        label: "user_purchased_premium",
      });
      clearCookie("clicked-purchase");
    }

    // The other cookies are set in `trackPlanPurchaseStart()`
    const plans: Plan[] = [
      { plan: "premium", billing_period: "yearly" },
      { plan: "premium", billing_period: "monthly" },
      { plan: "phones", billing_period: "yearly" },
      { plan: "phones", billing_period: "monthly" },
      { plan: "bundle" },
    ];
    plans.forEach((plan) => {
      const hasClickedPurchaseButtonCookie =
        getCookie(getCookieId(plan)) === "true";
      if (
        hasClickedPurchaseButtonCookie &&
        profileData?.has_premium &&
        (plan.plan === "premium" || profileData?.has_phone)
      ) {
        gaEvent({
          category: getGaCategory(plan),
          action: "Completed purchase",
          label: "user_purchased_premium",
        });
        clearCookie(getCookieId(plan));
      }
    });
  }, [profileData, gaEvent]);
};
