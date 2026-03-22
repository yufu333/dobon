// cards.js
// c0.svg = 裏面
// c1.svg ～ c52.svg = 表面カード

(function () {

  const BASE_URL = "https://yufu333.github.io/cards_assets/cards_img/";

  const TOTAL_CARDS = 52;  // 表面は1～52

  window.cards = {

    baseUrl: BASE_URL,

    total: TOTAL_CARDS,

    /**
     * 指定番号のカードURLを返す
     * @param {number} index
     * 0 = 裏面 (c0.svg)
     * 1～52 = 表面 (c1.svg～c52.svg)
     */
    getUrl: function (index) {

      if (typeof index !== "number") {
        console.error("index must be number");
        return "";
      }

      if (index < 0 || index > TOTAL_CARDS) {
        console.error("index out of range:", index);
        return "";
      }

      return BASE_URL + "c" + index + ".svg";
    }

  };

})();