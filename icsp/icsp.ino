#define ICSP_PIN_DAT 17
#define ICSP_PIN_CLK 18
#define HV 19
#define VDD 15

// Delay configuration for ICSP
#define ICSP_DELAY_CLK 2
#define ICSP_DELAY_DLY 10

// Variables to hold command args and data
static char cmd_args[4];
static char cmd_data[128];

static bool programming_mode = false;
static char startup_seq[] = {'M', 'C', 'H', 'P'};

void command(char cmd);
void start_programming(void);
void read_words(void);

void icsp_pins_out(void);
void icsp_pins_low(void);

#define CLK_HIGH()  digitalWrite(ICSP_PIN_CLK, HIGH); delayMicroseconds(ICSP_DELAY_CLK)
#define CLK_LOW()   digitalWrite(ICSP_PIN_CLK, LOW); delayMicroseconds(ICSP_DELAY_CLK)
#define CLK_CYCLE() CLK_HIGH(); CLK_LOW()

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(5000); // 5sec timeout

  while (!Serial) {}
  pinMode(HV, OUTPUT);
  pinMode(VDD, OUTPUT);
  digitalWrite(HV, HIGH);
  digitalWrite(VDD, LOW);
}

void loop() {
  char cmd;
  // Read command byte
  if (Serial.available()) {
    cmd = Serial.read();
    command(cmd);
  }
}


void command(char cmd) {
  switch (cmd) {
    case 's': // Start programming mode
      start_programming();
    break;
    
    case 'l':
      start_programming(true);
    break;

    case 'x': // Exit programming mode
      exit_programming();
    break;
    
    case 'r': // Read words
      read_words();
    break;
      
    case 'w': // Write words
      write_words();
    break;
    
    case 'e': // Erase row
      erase_row();
    break;
    
    case 'b': // Erase bulk
      bulk_erase();
    break;
    
    default:
//      Serial.print(cmd);
      Serial.print('U');
      break;
  }
}

// Programmer commands

void start_programming(bool lvp = false) {
  
  // Set pins to outputs in a low state.
  icsp_pins_out();
  icsp_pins_low();
  delayMicroseconds(260);
  
  if (lvp) {
    digitalWrite(HV, HIGH)
    digitalWrite(VDD, HIGH)
    delay(1);
    for (int i=0; i < 4; i++) {
      // Shift out the character MSb first
      clockOut(startup_seq[i]);
    }
  } else {
    digitalWrite(HV, LOW);
    delayMicroseconds(260);
    digitalWrite(VDD, HIGH);
  }

  Serial.write('K');
}

void exit_programming(void) {

  digitalWrite(HV, HIGH);
  delayMicroseconds(260);
  digitalWrite(VDD, LOW);

//  delay(1);

  // Tristate pins
  icsp_pins_in();
}

// This gets called before receiving any of the arugments
void read_words(void) {
  if (Serial.readBytes(cmd_args, 4) != 4) {
    // We didn't receive the correct amount of arguments in time
    // Return an error
    Serial.write('A');
    return;
  }

  // Address to start reading from
  int address = (cmd_args[0] << 8) | cmd_args[1];
  // Number of words to read
  int rLength = (cmd_args[2] << 8) | cmd_args[3];

  // Load PC with address
  icsp_load_pc(address);

  delay(5);

  // Read rLength number of words
  while (rLength) {
    int data = icsp_read_word(true);
    Serial.write(data>>8);
    Serial.write(data&0xFF);
    rLength--;
  }

  delayMicroseconds(ICSP_DELAY_DLY);
}

void write_words(void) {
  if (Serial.readBytes(cmd_args, 4) != 4) {
    // We didn't receive the correct amount of arguments in time
    // Return an error
    Serial.write('A');
    return;
  }
  
  // Address to start writing
  int address = (cmd_args[0] << 8) | cmd_args[1];
  // Number of words to write (len*2 bytes of data follows)
  int wLength = (cmd_args[2] << 8) | cmd_args[3];
  int wLenBytes = wLength * 2;

  if (Serial.readBytes(cmd_data, wLenBytes) != wLenBytes) {
    // We didn't receive the correct amount of data in time
    // Return an error
    Serial.write('D');
    return;
  }

  icsp_load_pc(address);

  // Erase row (required for write)
  icsp_erase_row();

  // Load all data latches except one
  int i;
  for (i=0; i < wLenBytes-2; i+=2) {
    icsp_load_latch((cmd_data[i]<<8)|cmd_data[i+1], true);
    delayMicroseconds(ICSP_DELAY_DLY);
  }
  // Load last data latch without incrementing PC
  icsp_load_latch((cmd_data[i]<<8)|cmd_data[i+1], false);

  // Begin internal timed write
  icsp_begin_write();

  Serial.write('K');
}

void erase_row(void) {
  if (Serial.readBytes(cmd_args, 2) != 2) {
    // We didn't receive the correct amount of arguments in time
    // Return an error
    Serial.write('A');
    return;
  }

  int address = (cmd_args[0] << 8) | cmd_args[1];

  icsp_load_pc(address);

  icsp_erase_row();

  Serial.write('K');
}

void bulk_erase(void) {
  if (Serial.readBytes(cmd_args, 2) != 2) {
    // We didn't receive the correct amount of arguments in time
    // Return an error
    Serial.write('A');
    return;
  }

  int address = (cmd_args[0] << 8) | cmd_args[1];

  icsp_load_pc(address);

  icsp_bulk_erase();

  Serial.write('K');
}


// ICSP commands

#define ICSP_CMD_LOAD_PC 0x80
void icsp_load_pc(int addr) {
  // Shift out command
  clockOut(ICSP_CMD_LOAD_PC);

  delayMicroseconds(ICSP_DELAY_DLY);

  // Shift out address
  clockOutData(addr);

  delayMicroseconds(ICSP_DELAY_DLY);
}

#define ICSP_CMD_READ 0xFC
#define ICSP_CMD_READ_INC 0xFE
int icsp_read_word(bool inc) {
  // Shift out command
  if (inc) {
    clockOut(ICSP_CMD_READ_INC);
  } else {
    clockOut(ICSP_CMD_READ);
  }

  // Set DAT pin to input
  pinMode(ICSP_PIN_DAT, INPUT);

  delayMicroseconds(ICSP_DELAY_DLY);

  int ret = clockIn();

  // Sack DAT pin back to output
  pinMode(ICSP_PIN_DAT, OUTPUT);

  return ret;
}


#define ICSP_CMD_LOAD       0
#define ICSP_CMD_LOAD_INC   2
void icsp_load_latch(int data, bool inc) {
  // Shift out command
  if (inc) {
    clockOut(ICSP_CMD_LOAD_INC);
  } else {
    clockOut(ICSP_CMD_LOAD);
  }

  // Shift out word
  clockOutData(data);
}

#define ICSP_CMD_ERASE_ROW  0xF0
void icsp_erase_row(void) {
  // Shift out command
  clockOut(ICSP_CMD_ERASE_ROW);

  // delay for ERAR (2.8ms)
  delay(3);
}

#define ICSP_CMD_BULK_ERASE  0x18
void icsp_bulk_erase(void) {
  // Shift out command
  clockOut(ICSP_CMD_BULK_ERASE);

  // delay for ERAR (2.8ms)
  delay(3);
}

#define ICSP_CMD_WRITE 0xE0
void icsp_begin_write(void) {
  // Shift out command
  clockOut(ICSP_CMD_WRITE);

  // Wait for TPINT: PFM 2.8ms / ConfWord 5.6ms
  delay(5);
}


// Utils

void icsp_pins_out(void) {
  pinMode(ICSP_PIN_DAT, OUTPUT);
  pinMode(ICSP_PIN_CLK, OUTPUT);
}

void icsp_pins_in(void) {
  pinMode(ICSP_PIN_DAT, INPUT);
  pinMode(ICSP_PIN_CLK, INPUT);

}

void icsp_pins_low(void) {
  digitalWrite(ICSP_PIN_DAT, LOW);
  digitalWrite(ICSP_PIN_CLK, LOW);
}


// Clocks out a byte MSb first
void clockOut(char data) {
  for (int i=7; i >= 0; i--) {
    // Set DAT to data bit
    digitalWrite(ICSP_PIN_DAT, ((data>>i)&1));
    // Cycle clock
    CLK_CYCLE();
  }
}

// Clock out a 16-bit payload MSb first, with 7 start/1 stop bits (0's)
void clockOutData(int data) {
  
  // Clock out 1 start + 6 padding bits 
  digitalWrite(ICSP_PIN_DAT, LOW); // Use 0's as padding
  for (int i=0; i < 7; i++) {
    CLK_CYCLE();
  }
  
  // Clock out 16-bit data MSb first
  for (int i=15; i >= 0; i--) {
    // Set DAT to data bit
    digitalWrite(ICSP_PIN_DAT, ((data>>i)&1));
    CLK_CYCLE();
  }
  
  // Clock out stop bit
  digitalWrite(ICSP_PIN_DAT, LOW);
  CLK_CYCLE();
}

// Clocks in 24 bits, returns the a 16-bit payload
int clockIn(void) {
  int ret = 0;

  // 7 start bits
  for (int i=0; i < 7; i++) {
    CLK_CYCLE();
  }

  // 16-bit payload
  for (int i=15; i >=0; i--) {
    digitalWrite(ICSP_PIN_CLK, HIGH);
    delayMicroseconds(ICSP_DELAY_CLK);
    ret |= digitalRead(ICSP_PIN_DAT) << i;
    digitalWrite(ICSP_PIN_CLK, LOW);
    delayMicroseconds(ICSP_DELAY_CLK);
  }

  // Stop bit
  CLK_CYCLE();

  return ret;
}