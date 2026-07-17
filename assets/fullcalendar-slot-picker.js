(function () {
  function isoToLabel(iso) {
    var m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return iso;
    return m[3] + '/' + m[2] + '/' + m[1];
  }

  function hasFree(day) {
    return !!(day && Array.isArray(day.slots) && day.slots.some(function (s) { return !!s.available; }));
  }

  function periodFromTime(timeText) {
    var hour = Number(String(timeText || '').split(':')[0]);
    if (!Number.isFinite(hour)) return 'otros';
    if (hour < 12) return 'manana';
    if (hour < 18) return 'tarde';
    return 'noche';
  }

  function periodLabel(period) {
    if (period === 'manana') return 'Mañana';
    if (period === 'tarde') return 'Tarde';
    if (period === 'noche') return 'Noche';
    return 'Otros horarios';
  }

  function FullCalendarSlotPicker(opts) {
    this.calendarEl = opts.calendarEl;
    this.timesEl = opts.timesEl;
    this.selectedEl = opts.selectedEl;
    this.statusEl = opts.statusEl;
    this.titleEl = opts.titleEl || null;
    this.prevEl = opts.prevEl || null;
    this.nextEl = opts.nextEl || null;
    this.loadAvailability = opts.loadAvailability;
    this.onChange = opts.onChange || function () {};
    this.emptyText = typeof opts.emptyText === 'string'
      ? opts.emptyText
      : 'Selecciona una fecha disponible en el calendario por tu siguiente consulta';
    this.autoRefreshMs = Number(opts.autoRefreshMs || 0);
    this._refreshTimer = null;
    this._headerBound = false;
    this.days = [];
    this.dayMap = new Map();
    this.selectedDate = '';
    this.selectedTime = '';
    this.calendar = null;
  }

  FullCalendarSlotPicker.prototype._formatMonthLabel = function (date) {
    var formatter = new Intl.DateTimeFormat('es-ES', { month: 'long', year: 'numeric' });
    var label = formatter.format(date || new Date());
    return label.charAt(0).toUpperCase() + label.slice(1);
  };

  FullCalendarSlotPicker.prototype._syncHeader = function () {
    if (!this.titleEl || !this.calendar) return;
    this.titleEl.textContent = this._formatMonthLabel(this.calendar.getDate ? this.calendar.getDate() : new Date());
  };

  FullCalendarSlotPicker.prototype._bindHeaderControls = function () {
    if (this._headerBound) return;
    var self = this;
    if (this.prevEl) {
      this.prevEl.addEventListener('click', function () {
        if (!self.calendar) return;
        self.calendar.prev();
        self._syncHeader();
        self._markCells();
      });
    }
    if (this.nextEl) {
      this.nextEl.addEventListener('click', function () {
        if (!self.calendar) return;
        self.calendar.next();
        self._syncHeader();
        self._markCells();
      });
    }
    if (this.titleEl) {
      this.titleEl.addEventListener('click', function () {
        if (!self.calendar) return;
        self.calendar.today();
        self._syncHeader();
        self._markCells();
      });
    }
    this._headerBound = true;
  };

  FullCalendarSlotPicker.prototype._renderTimes = function () {
    if (!this.timesEl) return;
    this.timesEl.innerHTML = '';
    var timesPanel = this.timesEl.closest('.times-dynamic') || this.timesEl.closest('.med-times-dynamic') || this.timesEl.parentElement;

    var day = this.dayMap.get(this.selectedDate);
    if (!day) {
      if (timesPanel) {
        timesPanel.style.display = 'none';
      }
      if (this.emptyText) {
        var empty = document.createElement('div');
        empty.className = 'fc-time-empty';
        empty.textContent = this.emptyText;
        this.timesEl.appendChild(empty);
      }
      return;
    }

    if (timesPanel) {
      timesPanel.style.display = 'block';
    }

    var self = this;
    var groups = {
      manana: [],
      tarde: [],
      noche: [],
      otros: []
    };
    (day.slots || []).forEach(function (slot) {
      groups[periodFromTime(slot.time)].push(slot);
    });

    ['manana', 'tarde', 'noche', 'otros'].forEach(function (periodKey) {
      var slots = groups[periodKey] || [];
      if (!slots.length) return;

      var section = document.createElement('section');
      section.className = 'fc-time-group';

      var title = document.createElement('h4');
      title.className = 'fc-time-group-title';
      title.textContent = periodLabel(periodKey);
      section.appendChild(title);

      var grid = document.createElement('div');
      grid.className = 'fc-time-group-grid';

      slots.forEach(function (slot) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'fc-time-btn';
        btn.textContent = slot.time;
        if (!slot.available) {
          btn.classList.add('is-taken');
          btn.disabled = true;
        } else {
          btn.classList.add('is-free');
          if (slot.time === self.selectedTime) btn.classList.add('is-selected');
          btn.addEventListener('click', function () {
            self.selectedTime = slot.time;
            self.onChange({ date: self.selectedDate, time: self.selectedTime });
            self._renderTimes();
            self._renderSelected();
          });
        }
        grid.appendChild(btn);
      });

      section.appendChild(grid);
      self.timesEl.appendChild(section);
    });
  };

  FullCalendarSlotPicker.prototype._renderSelected = function () {
    if (!this.selectedEl) return;
    this.selectedEl.textContent = '';
  };

  FullCalendarSlotPicker.prototype._markCells = function () {
    if (!this.calendarEl) return;
    var self = this;
    this.calendarEl.querySelectorAll('.fc-daygrid-day').forEach(function (cell) {
      var iso = cell.getAttribute('data-date') || '';
      var day = self.dayMap.get(iso);
      cell.classList.remove('fc-slot-free', 'fc-slot-taken', 'fc-slot-out', 'fc-slot-selected');
      if (!day) {
        cell.classList.add('fc-slot-out');
        return;
      }
      if (hasFree(day)) {
        cell.classList.add('fc-slot-free');
      } else {
        cell.classList.add('fc-slot-taken');
      }
      if (self.selectedDate && iso === self.selectedDate) {
        cell.classList.add('fc-slot-selected');
      }
    });
  };

  FullCalendarSlotPicker.prototype._selectDate = function (iso) {
    var day = this.dayMap.get(iso);
    if (!day || !hasFree(day)) return;
    this.selectedDate = iso;
    var free = (day.slots || []).find(function (s) { return !!s.available; });
    this.selectedTime = free ? free.time : '';
    this.onChange({ date: this.selectedDate, time: this.selectedTime });
    this._markCells();
    this._renderTimes();
    this._renderSelected();
  };

  FullCalendarSlotPicker.prototype.clearSelection = function () {
    this.selectedDate = '';
    this.selectedTime = '';
    this.onChange({ date: '', time: '' });
    this._markCells();
    this._renderTimes();
    this._renderSelected();
  };

  FullCalendarSlotPicker.prototype.gotoToday = function () {
    if (!this.calendar) return;
    this.calendar.today();
    this._syncHeader();
    this._markCells();
  };

  FullCalendarSlotPicker.prototype.load = async function () {
    if (this.statusEl) this.statusEl.textContent = 'Cargando agenda en vivo...';
    try {
      var data = await this.loadAvailability();
      this.days = Array.isArray(data && data.days) ? data.days : [];
      this.dayMap = new Map(this.days.map(function (d) { return [d.date, d]; }));
      if (!this.days.length) throw new Error('Agenda vacia.');
    } catch (err) {
      if (this.statusEl) this.statusEl.textContent = (err && err.message) ? err.message : 'No se pudo cargar la agenda.';
      return;
    }

    if (this.statusEl) this.statusEl.textContent = '';

    var self = this;
    if (!window.FullCalendar || !window.FullCalendar.Calendar) {
      if (this.statusEl) this.statusEl.textContent = 'FullCalendar no disponible.';
      return;
    }

    if (this.calendar) this.calendar.destroy();

    this.calendar = new window.FullCalendar.Calendar(this.calendarEl, {
      locale: 'es',
      initialView: 'dayGridMonth',
      height: 'auto',
      fixedWeekCount: false,
      showNonCurrentDates: false,
      dayHeaderFormat: { weekday: 'short' },
      headerToolbar: false,
      dayMaxEventRows: false,
      dateClick: function (info) {
        self._selectDate(info.dateStr);
      },
      datesSet: function () {
        setTimeout(function () {
          self._syncHeader();
          self._markCells();
        }, 0);
      }
    });

    this.calendar.render();
    this._bindHeaderControls();
    this._syncHeader();

    var firstFree = this.days.find(function (d) { return hasFree(d); });
    if (firstFree) {
      this.calendar.gotoDate(firstFree.date);
    }
    this.selectedDate = '';
    this.selectedTime = '';
    this.onChange({ date: '', time: '' });
    this._renderTimes();
    this._renderSelected();
    this._markCells();

    this._startAutoRefresh();
  };

  FullCalendarSlotPicker.prototype._refreshDataOnly = async function () {
    var data = await this.loadAvailability();
    this.days = Array.isArray(data && data.days) ? data.days : [];
    this.dayMap = new Map(this.days.map(function (d) { return [d.date, d]; }));

    if (!this.days.length) {
      this.selectedDate = '';
      this.selectedTime = '';
      this._renderTimes();
      this._renderSelected();
      this._markCells();
      return;
    }

    var selected = this.dayMap.get(this.selectedDate || '');
    if (!selected || !hasFree(selected)) {
      this.selectedDate = '';
      this.selectedTime = '';
      this.onChange({ date: this.selectedDate, time: this.selectedTime });
    } else {
      var chosenStillFree = (selected.slots || []).some(function (s) {
        return s.time === this.selectedTime && !!s.available;
      }, this);
      if (!chosenStillFree) {
        var fallback = (selected.slots || []).find(function (s) { return !!s.available; });
        this.selectedTime = fallback ? fallback.time : '';
        this.onChange({ date: this.selectedDate, time: this.selectedTime });
      }
    }

    this._renderTimes();
    this._renderSelected();
    this._markCells();
  };

  FullCalendarSlotPicker.prototype._startAutoRefresh = function () {
    if (!this.autoRefreshMs || this.autoRefreshMs < 1000) return;
    if (this._refreshTimer) clearInterval(this._refreshTimer);
    var self = this;
    this._refreshTimer = setInterval(function () {
      self._refreshDataOnly().catch(function () {
        if (self.statusEl) self.statusEl.textContent = 'Actualización automática no disponible ahora.';
      });
    }, this.autoRefreshMs);
  };

  FullCalendarSlotPicker.prototype.stopAutoRefresh = function () {
    if (this._refreshTimer) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
  };

  window.FullCalendarSlotPicker = FullCalendarSlotPicker;
})();
