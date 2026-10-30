/* IMS front-end helpers: delete confirmation, product picker (Select2 + AJAX),
   dynamic line rows, barcode / QR scanning (FR-25). */
(function ($) {
    'use strict';

    // ---- POST + CSRF confirmation (replaces GET based deletes) -------------
    window.confirmDelete = function (url, text) {
        Swal.fire({
            title: 'Are you sure?', text: text || 'This record will be deleted!', icon: 'warning',
            showCancelButton: true, confirmButtonColor: '#d33', cancelButtonColor: '#3085d6',
            confirmButtonText: 'Yes, delete it!'
        }).then(function (result) {
            if (result.isConfirmed) {
                var form = document.getElementById('ims-post-form');
                form.action = url;
                form.submit();
            }
        });
    };
    $(document).on('submit', 'form[data-confirm]', function (e) {
        var form = this;
        if (form.dataset.confirmed) { return; }
        e.preventDefault();
        Swal.fire({title: 'Are you sure?', text: form.dataset.confirm, icon: 'question', showCancelButton: true})
            .then(function (r) { if (r.isConfirmed) { form.dataset.confirmed = '1'; form.submit(); } });
    });

    // ---- product picker ------------------------------------------------------
    function initPicker($el) {
        if ($el.data('select2')) { return; }
        $el.select2({
            theme: 'bootstrap4', width: '100%', placeholder: 'Search SKU / name / barcode...', allowClear: true,
            minimumInputLength: 0,
            ajax: {
                url: $el.data('url') || '/product/search/', dataType: 'json', delay: 250,
                data: function (p) { return {q: p.term || ''}; },
                processResults: function (d) { return d; }
            }
        });
        $el.on('select2:select', function (e) { $el.trigger('product:selected', [e.params.data]); });
    }
    window.initProductPickers = function (root) { $(root || document).find('select.js-product').each(function () { initPicker($(this)); }); };

    // ---- dynamic line rows (PO / SO / transfer) --------------------------------
    function bindLines() {
        var $body = $('#lines-body');
        if (!$body.length) { return; }
        var tpl = $('#line-template').html();
        function recalc() {
            var total = 0;
            $body.find('tr').each(function () {
                var q = parseFloat($(this).find('.line-qty').val()) || 0;
                var p = parseFloat($(this).find('.line-price').val()) || 0;
                var t = q * p;
                $(this).find('.line-total').text(t.toFixed(2));
                total += t;
            });
            $('#lines-subtotal').text(total.toFixed(2));
        }
        window.addLine = function () {
            var $row = $(tpl);
            $body.append($row);
            initPicker($row.find('select.js-product'));
            return $row;
        };
        $body.on('click', '.remove-line', function () { $(this).closest('tr').remove(); recalc(); });
        $body.on('input', '.line-qty, .line-price', recalc);
        $body.on('product:selected', 'select.js-product', function (e, data) {
            var $row = $(this).closest('tr');
            if ($row.find('.line-price').length && !parseFloat($row.find('.line-price').val())) {
                $row.find('.line-price').val($body.data('price-field') === 'cost' ? data.cost : data.price);
            }
            $row.find('.line-uom').text(data.uom);
            recalc();
        });
        $('#add-line').on('click', function () { addLine(); });
        if (!$body.find('tr').length) { addLine(); }
        recalc();
    }

    // ---- barcode scanning -------------------------------------------------------------
    // USB / Bluetooth scanners behave like a keyboard that types the code + Enter.
    function lookup(code, done) {
        $.getJSON('/product/lookup/', {barcode: code}).done(function (d) { done(d); })
            .fail(function () { done(null); });
    }
    function setPicker($sel, p) {
        $sel.find('option').remove();
        $sel.append(new Option(p.text, p.id, true, true)).trigger('change');
        $sel.trigger('product:selected', [p]);
    }
    $(document).on('keydown', '.js-barcode', function (e) {
        if (e.key !== 'Enter') { return; }
        e.preventDefault();
        var $in = $(this), code = $in.val().trim();
        if (!code) { return; }
        lookup(code, function (p) {
            if (!p) { Swal.fire({toast: true, position: 'top-end', icon: 'error', title: 'No product for "' + code + '"', showConfirmButton: false, timer: 2500}); return; }
            var $target = $($in.data('target'));
            if ($target.length) { setPicker($target, p); }
            $in.val('');
            $in.trigger('barcode:found', [p]);
        });
    });
    $('#scan-input').on('keydown', function (e) {
        if (e.key !== 'Enter') { return; }
        e.preventDefault();
        var code = $(this).val().trim();
        if (!code) { return; }
        lookup(code, function (p) {
            $('#scan-result').html(p
                ? '<div class="callout callout-success"><h5>' + $('<i>').text(p.sku).html() + '</h5><p>' + $('<i>').text(p.name).html() +
                  '<br>Price: ' + p.price + ' &middot; Cost: ' + p.cost + '</p><a href="/stock/?keyword=' + encodeURIComponent(p.sku) + '" class="btn btn-sm btn-primary">View stock</a></div>'
                : '<div class="callout callout-danger">No product found for this code.</div>');
            $('#scan-input').val('').focus();
        });
    });
    $('#scan-modal').on('shown.bs.modal', function () { $('#scan-input').focus(); });

    // Camera scanning with the HTML5 BarcodeDetector API (Chrome / Android). Falls back to manual entry.
    $(document).on('click', '.js-camera-scan', function () {
        var $target = $($(this).data('target'));
        if (!('BarcodeDetector' in window)) {
            Swal.fire('Camera scanning is not supported in this browser', 'Use a USB / Bluetooth scanner or type the code.', 'info');
            return;
        }
        var video = document.getElementById('scan-video') || $('<video playsinline class="w-100">').insertAfter($target.closest('.input-group'))[0];
        video.style.display = 'block';
        navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}}).then(function (stream) {
            video.srcObject = stream; video.play();
            var detector = new BarcodeDetector();
            var timer = setInterval(function () {
                detector.detect(video).then(function (codes) {
                    if (codes.length) {
                        clearInterval(timer);
                        stream.getTracks().forEach(function (t) { t.stop(); });
                        video.style.display = 'none';
                        $target.val(codes[0].rawValue);
                        $target.trigger($.Event('keydown', {key: 'Enter'}));
                    }
                });
            }, 400);
        }).catch(function () { Swal.fire('Camera unavailable', 'Allow camera access or type the code.', 'warning'); });
    });

    $(function () { initProductPickers(); bindLines(); });
})(jQuery);
