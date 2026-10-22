package org.bashir.vocalmidi;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.View;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Offline, paragraph-by-paragraph help; no WebView or visual-only navigation. */
public class HelpActivity extends Activity {
    private JSONArray sections;
    private ScrollView scroll;
    private LinearLayout root, contents;
    private TextView matches;
    private int current = -1;
    private String query = "";

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(12), dp(20), dp(24));
        scroll.addView(root);
        setContentView(scroll);
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        try (InputStream in = getAssets().open("help/guide.json");
             ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int n;
            while ((n = in.read(buffer)) != -1) bytes.write(buffer, 0, n);
            sections = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name())).getJSONArray("sections");
            if (saved != null) {
                query = saved.getString("query", "");
                current = saved.getInt("topic", -1);
            } else {
                String id = getIntent().getStringExtra("topic");
                for (int i = 0; i < sections.length(); i++) {
                    if (sections.getJSONObject(i).getString("id").equals(id)) current = i;
                }
            }
            if (current >= 0 && current < sections.length()) showTopic(current, false);
            else showContents(false);
            if (saved != null) {
                int y = saved.getInt("scroll", 0);
                scroll.post(() -> scroll.scrollTo(0, y));
            }
        } catch (Exception e) {
            root.removeAllViews();
            heading("Не удалось открыть справку");
            paragraph("Закройте этот экран и попробуйте снова. Подробности: " + Jobs.error(e));
            button(root, "Закрыть справку", this::finish);
        }
    }

    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }

    private TextView paragraph(String value) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(18);
        view.setTextColor(0xff202124);
        view.setPadding(0, dp(8), 0, dp(10));
        root.addView(view, new LinearLayout.LayoutParams(-1, -2));
        return view;
    }

    private TextView heading(String value) {
        TextView view = paragraph(value);
        view.setTextSize(24);
        view.setTypeface(null, android.graphics.Typeface.BOLD);
        if (Build.VERSION.SDK_INT >= 28) view.setAccessibilityHeading(true);
        return view;
    }

    private Button button(LinearLayout parent, String label, Runnable action) {
        Button view = new Button(this);
        view.setText(label);
        view.setAllCaps(false);
        view.setTextSize(17);
        view.setMinHeight(dp(56));
        parent.addView(view, new LinearLayout.LayoutParams(-1, -2));
        view.setOnClickListener(v -> action.run());
        return view;
    }

    private void focusTitle(TextView title) {
        scroll.post(() -> {
            scroll.scrollTo(0, 0);
            title.performAccessibilityAction(AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS, null);
        });
    }

    private void closeKeyboard() {
        InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
        if (keyboard != null) keyboard.hideSoftInputFromWindow(root.getWindowToken(), 0);
    }

    private void showContents(boolean focus) {
        closeKeyboard();
        current = -1;
        root.removeAllViews();
        TextView title = heading("Подробная справка простым языком");
        paragraph("Начните с первого запуска или выберите тему. Знать ноты не нужно. " +
            "Справка работает без интернета. Для поиска введите слово: например, паузы, сдвиг или сохранить.");
        button(root, "Закрыть справку и вернуться в приложение", this::finish);
        TextView label = paragraph("Поиск по названиям и тексту справки");
        EditText search = new EditText(this);
        search.setId(View.generateViewId());
        label.setLabelFor(search.getId());
        search.setInputType(InputType.TYPE_CLASS_TEXT);
        search.setSingleLine(true);
        search.setTextSize(18);
        search.setMinHeight(dp(56));
        search.setText(query);
        root.addView(search, new LinearLayout.LayoutParams(-1, -2));
        button(root, "Очистить поиск и показать все темы", () -> search.setText(""));
        matches = paragraph("");
        matches.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        contents = new LinearLayout(this);
        contents.setOrientation(LinearLayout.VERTICAL);
        root.addView(contents, new LinearLayout.LayoutParams(-1, -2));
        filterContents();
        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                query = s.toString();
                filterContents();
            }
            @Override public void afterTextChanged(Editable s) {}
        });
        // Keep the keyboard closed until the reader explicitly opens the search field.
        root.setFocusableInTouchMode(true);
        root.requestFocus();
        if (focus) focusTitle(title);
    }

    private static String normalized(String text) {
        return text.toLowerCase(Locale.ROOT).replace('ё', 'е');
    }

    private void filterContents() {
        contents.removeAllViews();
        String[] words = normalized(query.trim()).split("\\s+");
        int count = 0;
        for (int i = 0; i < sections.length(); i++) {
            JSONObject section = sections.optJSONObject(i);
            if (section == null) continue;
            String haystack = normalized(section.optString("title") + " " + section.optJSONArray("paragraphs"));
            boolean found = true;
            for (String word : words) if (!haystack.contains(word)) found = false;
            if (found) {
                final int topic = i;
                button(contents, section.optString("title"), () -> showTopic(topic, true));
                count++;
            }
        }
        matches.setText(count == 0 ? "Совпадений нет. Попробуйте другое слово или очистите поиск."
            : "Доступно тем: " + count + ". Выберите тему ниже.");
    }

    private void showTopic(int index, boolean focus) {
        JSONObject section = sections.optJSONObject(index);
        if (section == null) { showContents(focus); return; }
        closeKeyboard();
        current = index;
        root.removeAllViews();
        TextView title = heading(section.optString("title"));
        paragraph("Раздел " + (index + 1) + " из " + sections.length());
        button(root, "К оглавлению и поиску", () -> showContents(true));
        button(root, "Закрыть справку и вернуться в приложение", this::finish);
        JSONArray paragraphs = section.optJSONArray("paragraphs");
        if (paragraphs != null) for (int i = 0; i < paragraphs.length(); i++) paragraph(paragraphs.optString(i));
        if (index > 0) button(root, "Предыдущая тема: " + sections.optJSONObject(index - 1).optString("title"),
            () -> showTopic(index - 1, true));
        if (index + 1 < sections.length()) button(root, "Следующая тема: " + sections.optJSONObject(index + 1).optString("title"),
            () -> showTopic(index + 1, true));
        button(root, "К оглавлению и поиску", () -> showContents(true));
        if (focus) focusTitle(title);
        else scroll.scrollTo(0, 0);
    }

    @Override protected void onSaveInstanceState(Bundle saved) {
        saved.putInt("topic", current);
        saved.putString("query", query);
        saved.putInt("scroll", scroll.getScrollY());
        super.onSaveInstanceState(saved);
    }
}
